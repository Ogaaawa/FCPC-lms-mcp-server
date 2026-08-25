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

# Moodle's internal module names read badly in an answer ("Assign: Essay 1").
ACTIVITY_LABELS = {
    "assign": "Assignment",
    "quiz": "Quiz",
    "forum": "Forum",
    "lesson": "Lesson",
    "workshop": "Workshop",
    "feedback": "Feedback",
    "choice": "Choice",
    "data": "Database",
    "scorm": "SCORM package",
    "chat": "Chat",
}


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

    async def get_course_contents(self, course_id: int) -> str:
        """What is actually inside a course: sections and their activities.

        Only works for a course the user is enrolled in; Moodle answers
        `errorcoursecontextnotvalid` for anything else. Sections with nothing
        visible in them are left out, since an empty course template
        otherwise produces pages of "New section".
        """
        contents = await self.call("core_course_get_contents", courseid=course_id)
        if contents is None:
            return (
                f"Could not read course {course_id}. You may not be enrolled in it."
            )

        blocks = []
        for section in contents:
            if not section.get("uservisible", True):
                continue

            entries = []
            for module in section.get("modules") or []:
                if not module.get("uservisible", True):
                    continue
                label = ACTIVITY_LABELS.get(module.get("modname")) or (
                    module.get("modplural") or module.get("modname") or "Item"
                )
                line = f"  - {label}: {module.get('name') or 'Untitled'}"
                if module.get("url"):
                    line += f"\n    {module['url']}"
                entries.append(line)

            if not entries:
                continue

            title = strip_html(section.get("name")) or f"Section {section.get('section')}"
            summary = strip_html(section.get("summary"))
            block = title + (f"\n  {summary}" if summary else "")
            blocks.append(block + "\n" + "\n".join(entries))

        if not blocks:
            return f"Course {course_id} has no visible activities yet."
        return "\n\n".join(blocks)

    async def get_course_announcements(self, course_id: int | None = None,
                                       limit: int = 5) -> str:
        """Posts in each course's Announcements forum.

        Teachers put most of their notices here rather than in messages. With
        no course_id every enrolled course is checked, which costs one request
        per course, so a single course should be named where it is known.
        """
        userid = await self.get_userid()

        if course_id is not None:
            courses = [{"id": course_id, "fullname": f"Course {course_id}"}]
            named = await self.call("core_course_get_courses_by_field",
                                    field="id", value=course_id)
            for c in (named or {}).get("courses", []):
                courses = [{"id": c["id"], "fullname": c.get("fullname")}]
        else:
            enrolled = await self.call("core_enrol_get_users_courses", userid=userid)
            if enrolled is None:
                return "Could not retrieve your courses."
            courses = enrolled
            if not courses:
                return "You are not enrolled in any courses."

        results = []
        for course in courses:
            forums = await self.call(
                "mod_forum_get_forums_by_courses", **{"courseids[0]": course["id"]}
            )
            for forum in forums or []:
                # "news" is the internal type of the Announcements forum.
                if forum.get("type") != "news":
                    continue

                posts = await self.call(
                    "mod_forum_get_forum_discussions",
                    forumid=forum["id"], perpage=max(limit, 1), page=0,
                )
                for post in (posts or {}).get("discussions", [])[:limit]:
                    subject = strip_html(post.get("subject") or post.get("name"))
                    body = strip_html(post.get("message"))
                    author = post.get("userfullname") or "Unknown"
                    when = unix_to_jst_str(post.get("created"))

                    block = f"Course: {course.get('fullname')}\n"
                    block += f"Announcement: {subject or '(no subject)'}\n"
                    block += f"Posted by {author}" + (f" on {when}" if when else "")
                    if body:
                        block += f"\n{body}"
                    results.append(block)

        if not results:
            return "There are no announcements in your courses."
        return "\n\n".join(results)

    async def get_my_grades(self) -> str:
        """The overall grade in each course.

        Moodle returns course ids only, so the enrolment list is fetched as
        well to put a name against each one.
        """
        userid = await self.get_userid()
        data = await self.call("gradereport_overview_get_course_grades", userid=userid)
        if data is None:
            return "Could not retrieve your grades."

        grades = data.get("grades") or []
        if not grades:
            return "No grades have been recorded for you yet."

        courses = await self.call("core_enrol_get_users_courses", userid=userid)
        names = {c["id"]: c.get("fullname") for c in (courses or []) if c.get("id")}

        lines = []
        for entry in grades:
            courseid = entry.get("courseid")
            name = names.get(courseid) or f"Course {courseid}"

            # Moodle writes "-" for a course with nothing graded yet.
            grade = strip_html(entry.get("grade"))
            if not grade or grade == "-":
                grade = "not graded yet"

            line = f"{name}: {grade}"
            if entry.get("rank"):
                line += f" (rank {entry['rank']})"
            lines.append(line)

        return "Your grades:\n" + "\n".join(lines)

    async def get_upcoming_deadlines(self, days: int = 14, limit: int = 30) -> str:
        """Every dated item across all courses, in one call.

        Moodle's own calendar already gathers assignments, quizzes and
        anything else with a deadline, so this asks it once instead of walking
        each course. Times come back formatted in the user's own timezone;
        we only format them ourselves if Moodle did not.
        """
        now = int(datetime.now().timestamp())
        data = await self.call(
            "core_calendar_get_action_events_by_timesort",
            timesortfrom=now,
            timesortto=now + days * 86400,
            limitnum=limit,
        )
        if data is None:
            return "Could not retrieve your deadlines."

        events = data.get("events") or []
        if not events:
            return f"Nothing is due in the next {days} days."

        results = []
        for event in events:
            course = (event.get("course") or {}).get("fullname") or "No course"
            what = event.get("activityname") or event.get("name") or "Untitled"
            module = event.get("modulename") or ""
            kind = ACTIVITY_LABELS.get(module) or (module.title() if module else "Event")

            when = (
                strip_html(event.get("formattedtime"))
                or unix_to_jst_str(event.get("timesort"))
                or "no date given"
            )
            if event.get("overdue"):
                when = f"{when} (overdue)"

            results.append(f"Course: {course}\n{kind}: {what}\nDue: {when}")

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

    async def check_notifications(self, unread_only: bool = True, limit: int = 10) -> str:
        """Moodle's notifications, which are not the same thing as messages.

        Deadline reminders, grading notices, forum posts and security alerts
        all arrive here, never in the messaging inbox, so a student asking
        "did I miss anything?" needs this as well as check_new_messages.
        """
        userid = await self.get_userid()
        data = await self.call(
            "message_popup_get_popup_notifications",
            useridto=userid,
            limit=max(limit, 1),
            offset=0,
        )
        if data is None:
            return "Could not retrieve your notifications."

        notifications = data.get("notifications") or []
        if unread_only:
            notifications = [n for n in notifications if not n.get("read")]

        if not notifications:
            return (
                "You have no unread notifications."
                if unread_only
                else "You have no notifications."
            )

        results = []
        for note in notifications:
            subject = strip_html(
                note.get("subject") or note.get("shortenedsubject")
            ) or "(no subject)"
            when = note.get("timecreatedpretty") or unix_to_jst_str(
                note.get("timecreated")
            )
            body = strip_html(
                note.get("smallmessage") or note.get("text") or note.get("fullmessage")
            )

            block = f"[{when}] {subject}" if when else subject
            if body and body != subject:
                block += f"\n  {body}"
            if note.get("contexturl"):
                block += f"\n  Link: {note['contexturl']}"
            results.append(block)

        total = data.get("unreadcount")
        header = (
            f"You have {total} unread notification{'s' if total != 1 else ''}.\n\n"
            if unread_only and isinstance(total, int)
            else ""
        )
        return header + "\n\n".join(results)

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
