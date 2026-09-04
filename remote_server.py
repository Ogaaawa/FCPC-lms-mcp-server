"""Remote MCP server for Claude custom connectors (streamable HTTP + OAuth).

Everyone registers the same single URL:

    https://<public-host>/mcp

Claude opens the Moodle sign-in page by itself, and signing in issues an
access token for that person. The whole flow works in a phone browser.

Moodle tokens are never stored here. Each one is encrypted into the access
token and decrypted per request.

Run with:
    python remote_server.py --public-url https://xxxx.trycloudflare.com
"""
import argparse
import json
import os
import typing

import anyio

from dotenv import load_dotenv
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.routing import Route

import login_page
from moodle_client import MoodleClient
from oauth_provider import SCOPE, MoodleOAuthProvider

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

MOODLE_URL = os.getenv("MOODLE_URL")
IMPERSONATE = os.getenv("MOODLE_IMPERSONATE", "chrome131")

_provider: MoodleOAuthProvider | None = None
mcp: FastMCP | None = None


def known_methods() -> set[str]:
    """Every JSON-RPC method the MCP SDK is willing to parse.

    Read out of the SDK's own types so it cannot drift out of step with the
    version installed.
    """
    from mcp import types

    names: set[str] = set()
    for model in (types.ClientRequest, types.ClientNotification):
        for member in typing.get_args(model.model_fields["root"].annotation):
            field = member.model_fields.get("method")
            if field is None:
                continue
            literal = typing.get_args(field.annotation)
            if literal:
                names.add(literal[0])
    return names


KNOWN_METHODS = known_methods()


async def drain(receive):
    """Collect a whole request body from an ASGI receive channel."""
    chunks = []
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return None
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            return b"".join(chunks)


def replay(body: bytes):
    """Hand a body that has already been read to the app underneath.

    After the body, block instead of reporting a disconnect. The streaming
    response keeps a read pending for the life of the request, and answering
    it with http.disconnect cuts the response off halfway.
    """
    done = False

    async def receive():
        nonlocal done
        if done:
            await anyio.sleep_forever()
        done = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def unsupported(body: bytes):
    """Answer for a JSON-RPC call the SDK cannot parse, or None to pass it on.

    Clients probe for methods that are not in the protocol - Claude sends
    `server/discover`. Handing one of those to the SDK raises a validation
    error inside the session manager's task group, which kills the manager for
    the lifetime of the process: every later request then fails with "Task
    group is not initialized". So unknown methods are answered here instead.
    """
    try:
        payload = json.loads(body)
    except Exception:
        return None  # not JSON; let the SDK produce its own parse error

    batch = payload if isinstance(payload, list) else [payload]
    if not all(isinstance(m, dict) for m in batch):
        return None
    if all(m.get("method") in KNOWN_METHODS for m in batch):
        return None

    errors = [
        {
            "jsonrpc": "2.0",
            "id": m.get("id"),
            "error": {
                "code": -32601,
                "message": f"Method not found: {m.get('method')}",
            },
        }
        for m in batch
        if m.get("id") is not None
    ]
    if not errors:
        return b""  # notifications only: acknowledge and say nothing
    return json.dumps(errors if isinstance(payload, list) else errors[0]).encode()


def get_client() -> MoodleClient:
    """Return a Moodle client for whoever is making this request."""
    access = get_access_token()
    if access is None:
        raise RuntimeError("Not signed in. Reconnect the connector in Claude.")
    token = _provider.unseal(access.token)
    if not token:
        raise RuntimeError("Your sign-in has expired. Please connect again.")
    return MoodleClient(MOODLE_URL, token, impersonate=IMPERSONATE)


def build(public_url: str) -> FastMCP:
    """Assemble the MCP server with OAuth enabled."""
    global _provider, mcp

    _provider = MoodleOAuthProvider(public_url)
    mcp = FastMCP(
        "moodle_assistant",
        stateless_http=True,
        auth_server_provider=_provider,
        auth=AuthSettings(
            issuer_url=public_url,
            required_scopes=[SCOPE],
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
            ),
        ),
    )

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
    async def get_course_announcements(course_id: int | None = None,
                                       limit: int = 5) -> str:
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

    return mcp


def build_app(public_url: str):
    """Return the ASGI app, with the sign-in page and compatibility shims."""
    public = public_url.rstrip("/")
    server = build(public)
    inner = server.streamable_http_app()

    get_login, post_login, catch = login_page.make_routes(_provider, MOODLE_URL)
    inner.router.routes.append(Route("/login", get_login, methods=["GET"]))
    inner.router.routes.append(Route("/login", post_login, methods=["POST"]))
    inner.router.routes.append(Route("/catch", catch, methods=["GET"]))

    # RFC 9728: Claude reads this to find the authorization server.
    async def protected_resource(request):
        return JSONResponse({
            "resource": f"{public}/mcp",
            "authorization_servers": [public],
            "scopes_supported": [SCOPE],
            "bearer_methods_supported": ["header"],
        })

    inner.router.routes.append(
        Route("/.well-known/oauth-protected-resource", protected_resource, methods=["GET"])
    )

    mount = server.settings.streamable_http_path.rstrip("/")  # "/mcp"
    challenge = (
        f'Bearer resource_metadata="{public}/.well-known/oauth-protected-resource"'
    ).encode()

    async def app(scope, receive, send):
        if scope["type"] != "http":
            await inner(scope, receive, send)
            return

        # Normalise /mcp to /mcp/ ourselves. Letting Starlette redirect
        # hands back an http:// address through the tunnel, which breaks
        # the connection.
        if scope.get("path") == mount:
            scope = dict(scope)
            scope["path"] = mount + "/"
            scope["raw_path"] = (mount + "/").encode()

        # Intercept JSON-RPC calls the SDK would choke on, before they reach it.
        if scope["method"] == "POST" and scope.get("path", "").rstrip("/") == mount:
            body = await drain(receive)
            if body is None:
                return
            answer = unsupported(body)
            if answer is not None:
                await send({
                    "type": "http.response.start",
                    "status": 200 if answer else 202,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(answer)).encode())],
                })
                await send({"type": "http.response.body", "body": answer})
                return
            receive = replay(body)

        async def send_wrapper(message):
            # Every 401 must point at the authorization server.
            if message["type"] == "http.response.start" and message["status"] == 401:
                headers = list(message.get("headers") or [])
                if not any(k.lower() == b"www-authenticate" for k, _ in headers):
                    headers.append((b"www-authenticate", challenge))
                message = {**message, "headers": headers}
            await send(message)

        await inner(scope, receive, send_wrapper)

    return app


def main():
    parser = argparse.ArgumentParser(description="Moodle remote MCP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--public-url",
        required=True,
        help="Address this server is reachable at from the internet.",
    )
    args = parser.parse_args()

    if not MOODLE_URL:
        raise SystemExit("MOODLE_URL is missing from .env.")

    public = args.public_url.rstrip("/")
    app = build_app(public)

    import uvicorn

    print("=" * 60)
    print(" Give this URL to your students (the same one for everyone)")
    print()
    print(f"   {public}/mcp")
    print()
    print("=" * 60)

    # Access logs are off so that tokens never end up in a log file.
    uvicorn.run(
        app, host=args.host, port=args.port, access_log=False,
        proxy_headers=True, forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
