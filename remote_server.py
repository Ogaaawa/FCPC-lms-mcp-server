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
import os

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

    return mcp


def build_app(public_url: str):
    """Return the ASGI app, with the sign-in page and compatibility shims."""
    public = public_url.rstrip("/")
    server = build(public)
    inner = server.streamable_http_app()

    get_login, post_login = login_page.make_routes(_provider, MOODLE_URL)
    inner.router.routes.append(Route("/login", get_login, methods=["GET"]))
    inner.router.routes.append(Route("/login", post_login, methods=["POST"]))

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
