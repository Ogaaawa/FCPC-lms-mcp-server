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
