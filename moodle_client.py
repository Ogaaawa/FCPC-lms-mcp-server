"""Client for the Moodle web service API.

The token lives on the instance rather than in a module-level variable, so a
single process can serve many users at once. A long-running server creates one
client per request, using that user's own token:

    client = MoodleClient(url, that_students_token)
    print(await client.check_new_messages())

The local MCP server (server.py) just uses the single token from .env.
"""
import html
import re
import sys
from datetime import datetime, timedelta, timezone

from curl_cffi.requests import AsyncSession

# Cloudflare protection: the TLS fingerprint of a real browser is required.
# A standard HTTPS client gets HTTP 403 back - verified against the live site.
DEFAULT_IMPERSONATE = "chrome131"
JST = timezone(timedelta(hours=9))


def unix_to_jst_str(unix_ts) -> str:
    """Format a UNIX timestamp as a JST date and time."""
    if not unix_ts:
        return ""
    return datetime.fromtimestamp(unix_ts, tz=JST).strftime("%Y-%m-%d %H:%M:%S JST")


def strip_html(text: str) -> str:
    """Turn the HTML fragments Moodle returns into plain text."""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


class MoodleError(Exception):
    """Raised when Moodle reports an explicit failure."""


class MoodleClient:
    def __init__(self, base_url: str, token: str, impersonate: str = DEFAULT_IMPERSONATE):
        if not base_url or not token:
            raise ValueError("base_url and token are both required")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.impersonate = impersonate
        self._userid = None  # cached for the lifetime of this instance

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/webservice/rest/server.php"

    async def call(self, wsfunction: str, **params):
        """Call one web service function. Returns None on failure."""
        query = {
            "wstoken": self.token,
            "moodlewsrestformat": "json",
            "wsfunction": wsfunction,
        }
        query.update({k: v for k, v in params.items() if v is not None})

        try:
            async with AsyncSession() as session:
                response = await session.get(
                    self.endpoint, params=query, impersonate=self.impersonate, timeout=30
                )
        except Exception as e:
            print(f"HTTP request failed: {e}", file=sys.stderr)
            return None

        if response.status_code != 200:
            print(
                f"HTTP {response.status_code} from {self.endpoint} :: {response.text[:200]}",
                file=sys.stderr,
            )
            return None

        try:
            data = response.json()
        except Exception:
            # A Cloudflare challenge page is HTML, not JSON.
            print(f"Non-JSON response :: {response.text[:200]}", file=sys.stderr)
            return None

        # Moodle reports errors as HTTP 200 with an "exception" key.
        if isinstance(data, dict) and data.get("exception"):
            print(
                f"Moodle error [{data.get('errorcode')}]: {data.get('message')}",
                file=sys.stderr,
            )
            return None

        return data

    # --- basics ---------------------------------------------------------
    async def site_info(self):
        return await self.call("core_webservice_get_site_info")

    async def get_userid(self) -> int:
        if self._userid is not None:
            return self._userid
        data = await self.site_info()
        if not data or "userid" not in data:
            raise MoodleError("Could not read your Moodle account details.")
        self._userid = data["userid"]
        return self._userid

    # --- features -------------------------------------------------------
    async def get_courses(self) -> str:
        userid = await self.get_userid()
        courses = await self.call("core_enrol_get_users_courses", userid=userid)
        if courses is None:
            return "Could not retrieve your courses."
        if not courses:
            return "You are not enrolled in any courses."
        return "Your courses:\n" + "\n".join(
            f"{c['fullname']} (ID: {c['id']})" for c in courses
        )

    async def get_due_assignments(self, days: int) -> str:
        data = await self.call("mod_assign_get_assignments")
        if data is None:
            return "Could not retrieve your assignments."

        now = datetime.now()
        deadline = now + timedelta(days=days)
        results = []
        for course in data.get("courses", []):
            for a in course.get("assignments", []):
                ts = a.get("duedate", 0)
                due = datetime.fromtimestamp(ts) if ts else None
                if due and now <= due <= deadline:
                    results.append(
                        f"Course: {course.get('fullname')}\n"
                        f"Assignment: {a.get('name')}\n"
                        f"Due: {due.strftime('%Y-%m-%d')}\n"
                    )
        if not results:
            return f"Nothing is due in the next {days} days."
        return "\n\n".join(results)

    async def check_new_messages(self) -> str:
        userid = await self.get_userid()
        data = await self.call(
            "core_message_get_conversations", userid=userid, limitfrom=0, limitnum=10
        )
        if not data or "conversations" not in data:
            return "Could not retrieve your messages."

        unread = []
        for conv in data["conversations"]:
            if conv.get("isread", True):
                continue

            # "members" can come back empty, so never index into it blindly.
            members = conv.get("members") or []
            sender = members[0].get("fullname", "Unknown") if members else "Unknown"
            count = conv.get("unreadcount") or 0

            # Build each conversation from scratch so nothing carries over
            # from the previous one.
            lines = []
            for msg in conv.get("messages") or []:
                text = strip_html(msg.get("text"))
                sent_at = unix_to_jst_str(msg.get("timecreated"))
                lines.append(f"  [{sent_at}] {text}" if sent_at else f"  {text}")

            body = "\n".join(lines) if lines else "  (message body unavailable)"
            unread.append(f"From: {sender} ({count} unread)\n{body}")

        return "\n\n".join(unread) if unread else "You have no unread messages."

    async def get_pending_quizzes(self, days: int | None = None) -> str:
        userid = await self.get_userid()
        courses = await self.call("core_enrol_get_users_courses", userid=userid)
        if courses is None:
            return "Could not retrieve your courses."

        now = datetime.now()
        deadline = now + timedelta(days=days) if days else None

        pending = []
        for course in courses:
            quiz_resp = await self.call(
                "mod_quiz_get_quizzes_by_courses", **{"courseids[0]": course["id"]}
            )
            if quiz_resp is None:
                continue

            for quiz in quiz_resp.get("quizzes", []):
                ts = quiz.get("timedue")
                due = datetime.fromtimestamp(ts) if ts else None
                if deadline and due and not (now <= due <= deadline):
                    continue

                attempts_resp = await self.call(
                    "mod_quiz_get_user_attempts", quizid=quiz["id"], userid=userid
                )
                if attempts_resp is None:
                    continue
                attempts = attempts_resp.get("attempts", [])

                # Pending means: never attempted, or still in progress/overdue.
                if not attempts or any(
                    a["state"] in ("inprogress", "overdue") for a in attempts
                ):
                    pending.append(
                        f"Course: {course['fullname']}\n"
                        f"Quiz: {quiz['name']}\n"
                        f"Due: {due.strftime('%Y-%m-%d') if due else 'no deadline'}"
                    )

        return "\n\n".join(pending) if pending else "You have no pending quizzes."
