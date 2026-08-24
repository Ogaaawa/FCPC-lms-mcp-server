"""Claude のカスタムコネクタ用のリモート MCP サーバ（streamable HTTP）。

各利用者は自分専用の URL を1つ登録するだけで使える。

    https://<公開ホスト>/u/<Moodleトークン>/mcp

URL に含まれるトークンでその都度 Moodle クライアントを作るため、
サーバ側にトークンを保存しない。利用者どうしのデータも混ざらない。

起動:
    python remote_server.py                 # 127.0.0.1:8000
    python remote_server.py --port 9000
    python remote_server.py --host 0.0.0.0

URL はパスワードと同じ秘密情報なので、アクセスログには残さない。
"""
import argparse
import contextvars
import os
import re

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from moodle_client import MoodleClient

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

MOODLE_URL = os.getenv("MOODLE_URL")
IMPERSONATE = os.getenv("MOODLE_IMPERSONATE", "chrome131")

# リクエストごとの Moodle トークン
_token: contextvars.ContextVar[str | None] = contextvars.ContextVar("moodle_token", default=None)

# stateless_http にすると 1 リクエストが 1 セッションとして完結するため、
# リクエストごとに違うトークンを扱える。
mcp = FastMCP("moodle_assistant", stateless_http=True)


def get_client() -> MoodleClient:
    token = _token.get()
    if not token:
        raise RuntimeError(
            "この URL にはトークンが含まれていません。"
            "https://<ホスト>/u/<あなたのMoodleトークン>/mcp の形式で登録してください。"
        )
    if not MOODLE_URL:
        raise RuntimeError("サーバ側の .env に MOODLE_URL がありません。")
    return MoodleClient(MOODLE_URL, token, impersonate=IMPERSONATE)


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


# --- URL からトークンを取り出す ASGI ラッパ -----------------------------
# 例) /u/<token>/mcp  ->  内側の MCP アプリには /mcp として渡す
USER_PATH = re.compile(r"^/u/(?P<token>[A-Za-z0-9._~-]{8,128})(?P<rest>/.*)?$")

# Moodle のトークンは 32 桁の英数字。想定外の文字列は弾く。
_inner_app = mcp.streamable_http_app()


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        # セッションマネージャの起動・終了をそのまま内側に渡す
        await _inner_app(scope, receive, send)
        return

    if scope["type"] != "http":
        await _inner_app(scope, receive, send)
        return

    match = USER_PATH.match(scope.get("path", ""))
    if not match:
        await _plain_response(
            send, 404,
            "この URL は正しくありません。\n"
            "https://<ホスト>/u/<あなたのMoodleトークン>/mcp の形式で登録してください。\n",
        )
        return

    # 内側は Mount("/mcp") なので、末尾スラッシュ付きで渡す。
    # スラッシュ無しだと Starlette が /mcp/ へリダイレクトを返し、
    # その際に /u/<token> のプレフィックスが失われてしまう。
    mount = mcp.settings.streamable_http_path.rstrip("/")
    rest = match.group("rest") or ""
    suffix = rest[len(mount):] if rest.startswith(mount) else ""
    rest = mount + (suffix if suffix.startswith("/") else "/")

    inner_scope = dict(scope)
    inner_scope["path"] = rest
    inner_scope["raw_path"] = rest.encode()

    _token.set(match.group("token"))
    await _inner_app(inner_scope, receive, send)


async def _plain_response(send, status: int, body: str):
    data = body.encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"content-length", str(len(data)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": data})


def main():
    parser = argparse.ArgumentParser(description="Moodle リモート MCP サーバ")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    import uvicorn

    print(f"リモート MCP サーバを起動します: http://{args.host}:{args.port}")
    print("Claude に登録する URL の形式:")
    print(f"  http://{args.host}:{args.port}/u/<あなたのMoodleトークン>/mcp")
    print("（公開時は Cloudflare Tunnel などで HTTPS にしてください）")

    # トークンが URL に含まれるため、アクセスログは出さない
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
