"""Moodle の Web サービスを叩くクライアント。

トークンをモジュール変数ではなくインスタンスに持たせているため、
1プロセスで複数ユーザーぶんを扱える。Chat ボットのような
サーバ常駐型では、リクエストごとに利用者のトークンで生成する。

    client = MoodleClient(url, その学生のトークン)
    print(await client.check_new_messages())

ローカルの MCP サーバ（server.py）は .env の1人ぶんで使う。
"""
import html
import re
import sys
from datetime import datetime, timedelta, timezone

from curl_cffi.requests import AsyncSession

# Cloudflare 対策: ブラウザの TLS フィンガープリントを偽装する。
# 標準の HTTPS クライアントでは 403 を返されることを実測で確認済み。
DEFAULT_IMPERSONATE = "chrome131"
JST = timezone(timedelta(hours=9))


def unix_to_jst_str(unix_ts) -> str:
    """UNIX 時刻を JST の文字列にする。"""
    if not unix_ts:
        return ""
    return datetime.fromtimestamp(unix_ts, tz=JST).strftime("%Y-%m-%d %H:%M:%S JST")


def strip_html(text: str) -> str:
    """Moodle が返す HTML 断片をプレーンテキストにする。"""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


class MoodleError(Exception):
    """Moodle 側が明示的にエラーを返したとき。"""


class MoodleClient:
    def __init__(self, base_url: str, token: str, impersonate: str = DEFAULT_IMPERSONATE):
        if not base_url or not token:
            raise ValueError("base_url と token は必須です")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.impersonate = impersonate
        self._userid = None  # 同一インスタンス内で使い回す

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/webservice/rest/server.php"

    async def call(self, wsfunction: str, **params):
        """Web サービスを1回呼ぶ。失敗時は None を返す（例外にしない）。"""
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
            # Cloudflare のチャレンジ HTML などが返ると JSON 化に失敗する
            print(f"Non-JSON response :: {response.text[:200]}", file=sys.stderr)
            return None

        # Moodle はエラーもステータス 200 + JSON で返す
        if isinstance(data, dict) and data.get("exception"):
            print(
                f"Moodle error [{data.get('errorcode')}]: {data.get('message')}",
                file=sys.stderr,
            )
            return None

        return data

    # --- 基本情報 -------------------------------------------------------
    async def site_info(self):
        return await self.call("core_webservice_get_site_info")

    async def get_userid(self) -> int:
        if self._userid is not None:
            return self._userid
        data = await self.site_info()
        if not data or "userid" not in data:
            raise MoodleError("ユーザー情報を取得できませんでした。")
        self._userid = data["userid"]
        return self._userid

    # --- 各機能 ---------------------------------------------------------
    async def get_courses(self) -> str:
        userid = await self.get_userid()
        courses = await self.call("core_enrol_get_users_courses", userid=userid)
        if courses is None:
            return "コース情報の取得に失敗しました。"
        if not courses:
            return "登録されているコースはありません。"
        return "所属コース一覧:\n" + "\n".join(
            f"{c['fullname']} (ID: {c['id']})" for c in courses
        )

    async def get_due_assignments(self, days: int) -> str:
        data = await self.call("mod_assign_get_assignments")
        if data is None:
            return "課題情報の取得に失敗しました。"

        now = datetime.now()
        deadline = now + timedelta(days=days)
        results = []
        for course in data.get("courses", []):
            for a in course.get("assignments", []):
                ts = a.get("duedate", 0)
                due = datetime.fromtimestamp(ts) if ts else None
                if due and now <= due <= deadline:
                    results.append(
                        f"コース: {course.get('fullname')}\n"
                        f"課題名: {a.get('name')}\n"
                        f"〆切: {due.strftime('%Y-%m-%d')}\n"
                    )
        return "\n\n".join(results) if results else "指定期間内の課題は見つかりませんでした。"

    async def check_new_messages(self) -> str:
        userid = await self.get_userid()
        data = await self.call(
            "core_message_get_conversations", userid=userid, limitfrom=0, limitnum=10
        )
        if not data or "conversations" not in data:
            return "メッセージの取得に失敗しました。"

        unread = []
        for conv in data["conversations"]:
            if conv.get("isread", True):
                continue

            # members が空のこともあるので添字アクセスしない
            members = conv.get("members") or []
            sender = members[0].get("fullname", "不明") if members else "不明"
            count = conv.get("unreadcount") or 0

            # 会話ごとに組み立てる（前の会話の値を持ち越さない）
            lines = []
            for msg in conv.get("messages") or []:
                text = strip_html(msg.get("text"))
                sent_at = unix_to_jst_str(msg.get("timecreated"))
                lines.append(f"  [{sent_at}] {text}" if sent_at else f"  {text}")

            body = "\n".join(lines) if lines else "  (本文を取得できませんでした)"
            unread.append(f"送信者: {sender}（未読 {count} 件）\n{body}")

        return "\n\n".join(unread) if unread else "未読メッセージはありません。"

    async def get_pending_quizzes(self, days: int | None = None) -> str:
        userid = await self.get_userid()
        courses = await self.call("core_enrol_get_users_courses", userid=userid)
        if courses is None:
            return "コース情報の取得に失敗しました。"

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

                # 未着手、または進行中／期限超過のものだけ
                if not attempts or any(
                    a["state"] in ("inprogress", "overdue") for a in attempts
                ):
                    pending.append(
                        f"コース: {course['fullname']}\n"
                        f"小テスト名: {quiz['name']}\n"
                        f"〆切: {due.strftime('%Y-%m-%d') if due else 'なし'}"
                    )

        return "\n\n".join(pending) if pending else "未完了の小テストはありません。"
