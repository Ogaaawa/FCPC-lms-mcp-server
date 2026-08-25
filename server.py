"""MCP server for Moodle, over stdio.

Meant to run on one person's own machine, so it uses the single token from
.env. The Moodle logic lives in moodle_client.py and is shared with
remote_server.py, which serves many users at once.
"""
import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from moodle_client import MoodleClient

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

MOODLE_URL = os.getenv("MOODLE_URL")
TOKEN = os.getenv("MOODLE_TOKEN")
IMPERSONATE = os.getenv("MOODLE_IMPERSONATE", "chrome131")

mcp = FastMCP("moodle_assistant")


def get_client() -> MoodleClient:
    """Build a client from the settings in .env."""
    if not MOODLE_URL or not TOKEN:
        raise RuntimeError(
            "MOODLE_URL and MOODLE_TOKEN are missing from .env. "
            "Run the setup wizard (setup_gui.py) first."
        )
    return MoodleClient(MOODLE_URL, TOKEN, impersonate=IMPERSONATE)


@mcp.tool()
async def get_my_userid() -> int:
    """Return the Moodle user id of the currently authenticated user.

    Mainly an internal helper for the other tools. Takes no arguments.
    """
    return await get_client().get_userid()


@mcp.tool()
async def get_upcoming_deadlines(days: int = 14) -> str:
    """List everything with a deadline in the next `days` days, soonest first.

    Prefer this for any general "what is coming up?", "what is due this week?"
    or "what do I have to do?" question. It reads the user's Moodle calendar,
    so one call covers assignments, quizzes and every other dated activity
    across all their courses. Use get_due_assignments or get_pending_quizzes
    only when the question is specifically about one of those alone.

    Args:
        days: How many days ahead to look. 7 means the coming week.

    Returns:
        For each item: the course, what kind of activity it is, its name and
        when it is due, marked "(overdue)" where Moodle says so.
    """
    return await get_client().get_upcoming_deadlines(days)


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
    return await get_client().get_due_assignments(days)


@mcp.tool()
async def check_new_messages() -> str:
    """List the user's unread Moodle messages, newest conversations first.

    Use this for questions about messages, notifications from teachers or
    classmates, or anything like "do I have new messages?". Takes no arguments.

    Returns:
        For each unread conversation: the sender, the unread count and the
        message texts with their timestamps in JST.
    """
    return await get_client().check_new_messages()


@mcp.tool()
async def check_notifications(unread_only: bool = True, limit: int = 10) -> str:
    """List Moodle notifications: reminders, grading notices and alerts.

    Notifications are a separate inbox from messages. Deadline reminders,
    "your assignment was graded", forum posts and security alerts arrive here
    and never appear in check_new_messages, so use this for "did I miss
    anything?", "any updates?" or "any notifications?". When a student asks
    broadly whether they have missed something, it is worth calling both.

    Args:
        unread_only: True (the default) lists only what has not been read.
            Pass False to include notifications already seen.
        limit: How many to fetch. 10 by default.

    Returns:
        Each notification with when it arrived, its subject, a short body and
        a link where Moodle gave one.
    """
    return await get_client().check_notifications(unread_only, limit)


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
    return await get_client().get_pending_quizzes(days)


@mcp.tool()
async def get_course_contents(course_id: int) -> str:
    """List the sections and activities inside one course.

    Use this for "what is in this course?", "what are we covering in week 3?"
    or "where is the reading for <subject>?". It returns the course outline
    with a link to each activity, so it is the way to find material rather
    than deadlines.

    Only works for courses the user is enrolled in. Get the id from
    get_my_courses first.

    Args:
        course_id: The Moodle course id.

    Returns:
        Each section with its activities, their type and their links. Empty
        and hidden sections are left out.
    """
    return await get_client().get_course_contents(course_id)


@mcp.tool()
async def get_course_announcements(course_id: int | None = None, limit: int = 5) -> str:
    """Read the Announcements forum of one course, or of every course.

    Teachers post class-wide notices here - schedule changes, exam details,
    reminders - and those never arrive as messages or notifications. Use this
    for "any announcements?", "what did my teacher post?" or questions about a
    specific course's news.

    Args:
        course_id: Optional. The course to read. Omitting it checks every
            enrolled course, which is slower, so pass the id when the question
            names a course. Course ids come from get_my_courses.
        limit: How many recent posts per course. 5 by default.

    Returns:
        Each announcement with its course, subject, author, date and text.
    """
    return await get_client().get_course_announcements(course_id, limit)


@mcp.tool()
async def get_my_grades() -> str:
    """Show the overall grade the user has in each of their courses.

    Use this for "how am I doing?", "what are my grades?" or "what is my mark
    in <course>?". It reports the course total, not individual assignment
    marks. Courses where nothing has been graded yet are listed as such.
    Takes no arguments.

    Returns:
        One line per course with its grade, and the user's rank where Moodle
        publishes one.
    """
    return await get_client().get_my_grades()


@mcp.tool()
async def get_my_courses() -> str:
    """List every Moodle course the user is currently enrolled in.

    Use this for questions about which courses, subjects or classes the user is
    taking. Takes no arguments.

    Returns:
        A list of course full names with their Moodle course ids.
    """
    return await get_client().get_courses()


if __name__ == "__main__":
    mcp.run(transport="stdio")
