"""Report what a Moodle token can see, so you know which account you are on.

The connector holds one Moodle token at a time. When testing as a student and
then as a teacher, the single most common mistake is to believe the token was
swapped when it was not, and to read the old account's answers as the new
one's. Run this before and after every swap.

Usage:
    python check_token.py                 # the token in .env
    python check_token.py <token>
    python check_token.py <token> --teacher-probe
"""
import asyncio
import sys
import time

import moodle_auth
from moodle_client import MoodleClient

TEACHER_CALLS = [
    ("Enrolled users in a course", "core_enrol_get_enrolled_users"),
    ("Grade book for a course", "gradereport_grader_get_users_in_report"),
    ("Submissions for an assignment", "mod_assign_get_submissions"),
]


async def report(base_url: str, token: str, teacher_probe: bool) -> int:
    client = MoodleClient(base_url, token)

    info = await client.site_info()
    if not info:
        print("This token was refused. Check it is current and complete.")
        return 1

    print("Account")
    print(f"  Site      {info.get('sitename')}")
    print(f"  Name      {info.get('fullname')}")
    print(f"  Username  {info.get('username')}")
    print(f"  User id   {info.get('userid')}")
    print(f"  Site admin{'  yes' if info.get('userissiteadmin') else '  no'}")

    userid = info.get("userid")
    courses = await client.call("core_enrol_get_users_courses", userid=userid)
    courses = courses or []
    print(f"\nCourses ({len(courses)})")
    if not courses:
        print("  none - most tools will correctly answer 'nothing found'")
    for course in courses:
        print(f"  {course['id']:>6}  {course.get('fullname')}")

    print("\nWhat the tools have to work with")
    counts = {}

    assignments = await client.call("mod_assign_get_assignments")
    counts["assignments"] = sum(
        len(c.get("assignments") or []) for c in (assignments or {}).get("courses", [])
    )

    # Cloudflare rejects timesortto=2**31-1 outright, so ask for a year.
    events = await client.call(
        "core_calendar_get_action_events_by_timesort",
        timesortfrom=0, timesortto=int(time.time()) + 365 * 86400, limitnum=50,
    )
    counts["dated items (next year)"] = len((events or {}).get("events") or [])

    convs = await client.call(
        "core_message_get_conversations", userid=userid, limitfrom=0, limitnum=20
    )
    counts["unread conversations"] = sum(
        1 for c in (convs or {}).get("conversations", []) if not c.get("isread", True)
    )

    notes = await client.call(
        "message_popup_get_popup_notifications", useridto=userid, limit=20, offset=0
    )
    counts["unread notifications"] = sum(
        1 for n in (notes or {}).get("notifications", []) if not n.get("read")
    )

    grades = await client.call(
        "gradereport_overview_get_course_grades", userid=userid
    )
    counts["graded courses"] = len((grades or {}).get("grades") or [])

    quizzes = 0
    announcements = 0
    for course in courses:
        found = await client.call(
            "mod_quiz_get_quizzes_by_courses", **{"courseids[0]": course["id"]}
        )
        quizzes += len((found or {}).get("quizzes") or [])

        forums = await client.call(
            "mod_forum_get_forums_by_courses", **{"courseids[0]": course["id"]}
        )
        for forum in forums or []:
            if forum.get("type") != "news":
                continue
            posts = await client.call(
                "mod_forum_get_forum_discussions", forumid=forum["id"],
                perpage=20, page=0,
            )
            announcements += len((posts or {}).get("discussions") or [])
    counts["quizzes"] = quizzes
    counts["announcements"] = announcements

    for label, value in counts.items():
        marker = "  " if value else "  (empty) "
        print(f"  {label:24} {value}{'' if value else marker}")

    if not teacher_probe:
        return 0

    print("\nTeacher-only calls")
    if not courses:
        print("  no course to test against")
        return 0

    courseid = courses[0]["id"]
    print(f"  against course {courseid}")
    for label, fn in TEACHER_CALLS:
        if fn == "core_enrol_get_enrolled_users":
            data = await client.call(fn, courseid=courseid)
            size = len(data or [])
        elif fn == "gradereport_grader_get_users_in_report":
            data = await client.call(fn, courseid=courseid)
            size = len((data or {}).get("users") or [])
        else:
            found = await client.call(
                "mod_assign_get_assignments", **{"courseids[0]": courseid}
            )
            ids = [
                a["id"]
                for c in (found or {}).get("courses", [])
                for a in c.get("assignments", [])
            ]
            if not ids:
                print(f"  {label:34} no assignment in this course to test with")
                continue
            data = await client.call(fn, **{"assignmentids[0]": ids[0]})
            size = sum(
                len(a.get("submissions") or [])
                for a in (data or {}).get("assignments", [])
            )
        verdict = f"{size} row(s)" if size else "empty - no permission, or genuinely none"
        print(f"  {label:34} {verdict}")

    print("\n  Some of these report a refusal as an explicit nopermissions error")
    print("  above; others just answer with an empty list, which looks exactly")
    print("  like having no data. So run this with a student token and with a")
    print("  teacher token and compare: empty for one and populated for the")
    print("  other is what proves a teacher tool would work.")
    return 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    teacher_probe = "--teacher-probe" in sys.argv

    env = moodle_auth.read_env()
    base_url = env.get("MOODLE_URL")
    token = args[0] if args else env.get("MOODLE_TOKEN")

    if not base_url:
        raise SystemExit("MOODLE_URL is missing from .env.")
    if not token or token.startswith("your_"):
        raise SystemExit("No token given, and none saved in .env.")

    raise SystemExit(asyncio.run(report(base_url, token, teacher_probe)))


if __name__ == "__main__":
    main()
