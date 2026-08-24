from typing import Any
from curl_cffi.requests import AsyncSession
import json
from mcp.server.fastmcp import FastMCP
from datetime import datetime, timedelta, timezone
import re
import html
import os
import sys

# with open("config.json") as f:
#     config = json.load(f)

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

MOODLE_URL = os.getenv("MOODLE_URL")
TOKEN = os.getenv("MOODLE_TOKEN")
# Cloudflare 対策: ブラウザの TLS フィンガープリントを偽装する
IMPERSONATE = os.getenv("MOODLE_IMPERSONATE", "chrome131")

# MOODLE_URL = config["moodle"]["base_url"]
# TOKEN = config["moodle"]["token"]

mcp = FastMCP("moodle_assistant")

def unix_to_jst_str(unix_ts):
    # UTCのUNIXタイムスタンプをJST(UTC+9)に変換
    if not unix_ts:
        return ""

    dt_utc = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    dt_jst = dt_utc + timedelta(hours=9)
    return dt_jst.strftime("%Y-%m-%d %H:%M:%S JST")

async def async_get(url: str, params: dict) -> dict | None:
    try:
        async with AsyncSession() as client:
            response = await client.get(
                url, params=params, impersonate=IMPERSONATE, timeout=30
            )
    except Exception as e:
        print(f"HTTP request failed: {e}", file=sys.stderr)
        return None

    if response.status_code != 200:
        print(
            f"HTTP {response.status_code} from {url} :: {response.text[:200]}",
            file=sys.stderr,
        )
        return None

    try:
        data = response.json()
    except Exception:
        # Cloudflare のチャレンジ HTML などが返ると JSON 化に失敗する
        print(f"Non-JSON response from {url} :: {response.text[:200]}", file=sys.stderr)
        return None

    # Moodle はエラーもステータス 200 + JSON で返す
    if isinstance(data, dict) and data.get("exception"):
        print(
            f"Moodle error [{data.get('errorcode')}]: {data.get('message')}",
            file=sys.stderr,
        )
        return None

    return data

@mcp.tool()
async def get_my_userid() -> int:
    """Return the Moodle user id of the currently authenticated user.

    Mainly an internal helper for the other tools. Takes no arguments.
    """
    url = f"{MOODLE_URL}/webservice/rest/server.php"
    params = {
        "wstoken": TOKEN,
        "moodlewsrestformat": "json",
        "wsfunction": "core_webservice_get_site_info"
    }
    data = await async_get(url, params)
    if data and "userid" in data:
        return data["userid"]
    raise Exception("Failed to get user id")

@mcp.tool()
async def get_due_assignments(days: int) -> str:
    """List the user's Moodle assignments due within the next `days` days.

    Use this for questions about homework, assignments, submissions or their
    deadlines (e.g. "what is due this week?", "any assignments due soon?").

    Args:
        days: How many days ahead to look. For example 7 means the coming week.

    Returns:
        A human readable list of course name, assignment name and due date,
        or a message saying nothing is due in that period.
    """
    url = f"{MOODLE_URL}/webservice/rest/server.php"
    params = {
        "wstoken": TOKEN,
        "moodlewsrestformat": "json",
        "wsfunction": "mod_assign_get_assignments"
    }
    data = await async_get(url, params)
    if data is None:
        return "課題情報の取得に失敗しました。"

    now = datetime.now()
    deadline = now + timedelta(days=days)
    results = []
    for course in data.get("courses", []):
        for a in course.get("assignments", []):
            duedate_ts = a.get("duedate", 0)
            duedate = datetime.fromtimestamp(duedate_ts) if duedate_ts else None
            if duedate and now <= duedate <= deadline:
                results.append(f"コース: {course.get('fullname')}\n課題名: {a.get('name')}\n〆切: {duedate.strftime('%Y-%m-%d')}\n")

    return "\n\n".join(results) if results else "指定期間内の課題は見つかりませんでした。"

@mcp.tool()
async def check_new_messages() -> str:
    """List the user's unread Moodle messages, newest conversations first.

    Use this for questions about messages, notifications from teachers or
    classmates, or anything like "do I have new messages?". Takes no arguments.

    Returns:
        For each unread conversation: the sender, the unread count and the
        message texts with their timestamps in JST.
    """
    userid = await get_my_userid()
    url = f"{MOODLE_URL}/webservice/rest/server.php"
    params = {
        "wstoken": TOKEN,
        "moodlewsrestformat": "json",
        "wsfunction": "core_message_get_conversations",
        "userid": userid,
        "limitfrom": 0,
        "limitnum": 10
    }
    data = await async_get(url, params)
    if not data or "conversations" not in data:
        return "メッセージの取得に失敗しました。"

    unread_msgs = []
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
            # メッセージ本文はHTML形式のことが多いのでタグ除去してテキスト化
            text_plain = re.sub(r"<[^>]+>", "", msg.get("text") or "")
            text_plain = html.unescape(text_plain).strip()
            sent_at = unix_to_jst_str(msg.get("timecreated"))
            lines.append(f"  [{sent_at}] {text_plain}" if sent_at else f"  {text_plain}")

        body = "\n".join(lines) if lines else "  (本文を取得できませんでした)"
        unread_msgs.append(f"送信者: {sender}（未読 {count} 件）\n{body}")

    return "\n\n".join(unread_msgs) if unread_msgs else "未読メッセージはありません。"


@mcp.tool()
async def get_pending_quizzes(days: int | None = None) -> str:
    """List quizzes the user has not completed yet.

    Use this for questions about quizzes, tests or exams that still need to be
    taken. A quiz counts as pending when it has no attempt yet, or an attempt
    that is still in progress or overdue.

    Args:
        days: Optional. If given, only quizzes due within that many days are
            returned. If omitted, all pending quizzes are returned.

    Returns:
        A human readable list of course name, quiz name and due date.
    """
    userid = await get_my_userid()
    url = f"{MOODLE_URL}/webservice/rest/server.php"
    params = {
        "wstoken": TOKEN,
        "moodlewsrestformat": "json",
        "wsfunction": "core_enrol_get_users_courses",
        "userid": userid
    }
    courses = await async_get(url, params)
    if courses is None:
        return "コース情報の取得に失敗しました。"

    now = datetime.now()
    deadline = now + timedelta(days=days) if days else None

    pending_quizzes = []
    for course in courses:
        course_id = course["id"]
        course_name = course["fullname"]

        quiz_params = {
            "wstoken": TOKEN,
            "moodlewsrestformat": "json",
            "wsfunction": "mod_quiz_get_quizzes_by_courses",
            "courseids[0]": course_id
        }
        quiz_resp = await async_get(url, quiz_params)
        if quiz_resp is None:
            continue
        quizzes = quiz_resp.get("quizzes", [])

        for quiz in quizzes:
            duedate_ts = quiz.get("timedue")
            duedate = datetime.fromtimestamp(duedate_ts) if duedate_ts else None

            if deadline and duedate and not (now <= duedate <= deadline):
                continue

            attempt_params = {
                "wstoken": TOKEN,
                "moodlewsrestformat": "json",
                "wsfunction": "mod_quiz_get_user_attempts",
                "quizid": quiz["id"],
                "userid": userid
            }
            attempt_resp = await async_get(url, attempt_params)
            if attempt_resp is None:
                continue
            attempts = attempt_resp.get("attempts", [])

            # 未完了のクイズだけ
            if not attempts or any(a["state"] in ["inprogress", "overdue"] for a in attempts):
                pending_quizzes.append(f"コース: {course_name}\n小テスト名: {quiz['name']}\n〆切: {duedate.strftime('%Y-%m-%d') if duedate else 'なし'}")

    return "\n\n".join(pending_quizzes) if pending_quizzes else "未完了の小テストはありません。"

@mcp.tool()
async def get_my_courses() -> str:
    """List every Moodle course the user is currently enrolled in.

    Use this for questions about which courses, subjects or classes the user is
    taking. Takes no arguments.

    Returns:
        A list of course full names with their Moodle course ids.
    """

    userid = await get_my_userid()
    url = f"{MOODLE_URL}/webservice/rest/server.php"
    params = {
        "wstoken": TOKEN,
        "moodlewsrestformat": "json",
        "wsfunction": "core_enrol_get_users_courses",
        "userid": userid
    }
    courses = await async_get(url, params)
    if courses is None:
        return "コース情報の取得に失敗しました。"

    if not courses:
        return "登録されているコースはありません。"

    course_list = [f"{c['fullname']} (ID: {c['id']})" for c in courses]
    return "所属コース一覧:\n" + "\n".join(course_list)

if __name__ == "__main__":
    mcp.run(transport="stdio")
