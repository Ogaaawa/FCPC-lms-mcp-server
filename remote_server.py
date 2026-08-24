"""Claude のカスタムコネクタ用のリモート MCP サーバ（streamable HTTP + OAuth）。

学生は全員 同じ URL を1本登録するだけでよい。

    https://<公開ホスト>/mcp

Claude が自動で Moodle のログイン画面を開き、ログインするとその人の
トークンが払い出される。スマートフォンのブラウザだけで完結する。

Moodle のトークンはサーバに保存しない。アクセストークンに暗号化して
埋め込み、リクエストごとに復号して使う。

起動:
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
    """いま呼び出している利用者の Moodle クライアントを返す。"""
    access = get_access_token()
    if access is None:
        raise RuntimeError("ログインが必要です。Claude でコネクタを接続し直してください。")
    token = _provider.unseal(access.token)
    if not token:
        raise RuntimeError("ログインの有効期限が切れました。接続し直してください。")
    return MoodleClient(MOODLE_URL, token, impersonate=IMPERSONATE)


def build(public_url: str) -> FastMCP:
    """OAuth 付きの MCP サーバを組み立てる。"""
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
    """ログイン画面と互換用の処理を足した ASGI アプリを返す。"""
    public = public_url.rstrip("/")
    server = build(public)
    inner = server.streamable_http_app()

    get_login, post_login = login_page.make_routes(_provider, MOODLE_URL)
    inner.router.routes.append(Route("/login", get_login, methods=["GET"]))
    inner.router.routes.append(Route("/login", post_login, methods=["POST"]))

    # RFC 9728。Claude はここを見て認可サーバの場所を知る。
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

        # /mcp を /mcp/ に正規化する。リダイレクトさせるとトンネル越しに
        # http:// のアドレスが返り、接続が壊れることがあるため。
        if scope.get("path") == mount:
            scope = dict(scope)
            scope["path"] = mount + "/"
            scope["raw_path"] = (mount + "/").encode()

        async def send_wrapper(message):
            # 401 には認可サーバの場所を必ず添える（MCP の作法）
            if message["type"] == "http.response.start" and message["status"] == 401:
                headers = list(message.get("headers") or [])
                if not any(k.lower() == b"www-authenticate" for k, _ in headers):
                    headers.append((b"www-authenticate", challenge))
                message = {**message, "headers": headers}
            await send(message)

        await inner(scope, receive, send_wrapper)

    return app


def main():
    parser = argparse.ArgumentParser(description="Moodle リモート MCP サーバ")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--public-url",
        required=True,
        help="外から見えるアドレス（例: https://xxxx.trycloudflare.com）",
    )
    args = parser.parse_args()

    if not MOODLE_URL:
        raise SystemExit(".env に MOODLE_URL がありません。")

    public = args.public_url.rstrip("/")
    app = build_app(public)

    import uvicorn

    print("=" * 60)
    print(" 学生に伝える URL（全員これ1本）")
    print()
    print(f"   {public}/mcp")
    print()
    print("=" * 60)

    # トークンを含むリクエストが記録されないようアクセスログは出さない
    uvicorn.run(
        app, host=args.host, port=args.port, access_log=False,
        proxy_headers=True, forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
