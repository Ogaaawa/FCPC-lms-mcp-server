"""Check that this installation works, end to end.

Run this after setup, or after changing anything, to confirm the server still
behaves. Everything here is automatic; the few steps that need a real browser
are listed at the end.

    python selftest.py            # all checks
    python selftest.py --offline  # skip anything that touches the network

Exit code is 0 when every check passes, 1 otherwise.
"""
import argparse
import asyncio
import base64
import hashlib
import json
import os
import secrets
import socket
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

PASSED = []
FAILED = []
SKIPPED = []


def check(label, ok, detail=""):
    """Record one result and print it."""
    mark = "PASS" if ok else "FAIL"
    (PASSED if ok else FAILED).append(label)
    print(f"  [{mark}] {label}")
    if detail:
        print(f"         {detail}")
    return ok


def skip(label, why):
    SKIPPED.append(label)
    print(f"  [SKIP] {label}")
    print(f"         {why}")


def section(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------- settings
def check_settings():
    section("1. Settings")
    url = os.getenv("MOODLE_URL")
    token = os.getenv("MOODLE_TOKEN")

    ok_url = check(
        ".env has MOODLE_URL",
        bool(url) and not url.startswith("your_"),
        url or "not set - run setup_gui.py",
    )
    ok_token = check(
        ".env has MOODLE_TOKEN",
        bool(token) and not token.startswith("your_"),
        f"{len(token)} characters" if token else "not set - run setup_gui.py",
    )
    return ok_url and ok_token


# ------------------------------------------------------------------ moodle
def check_moodle():
    section("2. Moodle connection")
    from curl_cffi import requests as cc

    url = os.getenv("MOODLE_URL").rstrip("/")
    token = os.getenv("MOODLE_TOKEN")
    endpoint = f"{url}/webservice/rest/server.php"
    params = {
        "wstoken": token,
        "moodlewsrestformat": "json",
        "wsfunction": "core_webservice_get_site_info",
    }

    try:
        r = cc.get(endpoint, params=params, impersonate="chrome131", timeout=30)
        data = r.json()
    except Exception as e:
        check("Moodle reachable", False, f"{type(e).__name__}: {e}")
        return False

    if not check("Token is accepted", bool(data.get("sitename")),
                 data.get("sitename") or str(data)[:80]):
        return False
    check("Signed in as", True, f"{data.get('fullname')} ({data.get('username')})")

    functions = {f["name"] for f in data.get("functions", [])}
    needed = [
        "mod_assign_get_assignments",
        "core_message_get_conversations",
        "core_enrol_get_users_courses",
        "mod_quiz_get_quizzes_by_courses",
        "mod_quiz_get_user_attempts",
    ]
    missing = [n for n in needed if n not in functions]
    check("All required web service functions are available",
          not missing, "missing: " + ", ".join(missing) if missing else "5 of 5")

    # Whether the browser TLS fingerprint is actually needed here.
    try:
        import httpx
        plain = httpx.get(endpoint, params=params, timeout=20)
        needs_impersonation = plain.status_code != 200
    except Exception:
        needs_impersonation = True
    print(f"  [INFO] Browser TLS fingerprint required: "
          f"{'yes (site is behind a filter)' if needs_impersonation else 'no'}")
    return True


# ----------------------------------------------------------- local mcp
def check_local_mcp():
    section("3. Local MCP server (server.py)")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        venv_py = os.path.join(ROOT, "venv", "bin", "python")
        params = StdioServerParameters(
            command=venv_py if os.path.exists(venv_py) else sys.executable,
            args=[os.path.join(ROOT, "server.py")],
            cwd=ROOT,
            env=dict(os.environ),
        )
        devnull = open(os.devnull, "w")
        try:
            async with stdio_client(params, errlog=devnull) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = [t.name for t in (await session.list_tools()).tools]
                    res = await session.call_tool("get_my_userid", {})
                    text = "".join(
                        c.text for c in res.content if getattr(c, "type", "") == "text"
                    )
                    return tools, text.strip()
        finally:
            devnull.close()

    try:
        tools, userid = asyncio.run(run())
    except Exception as e:
        check("Server starts over stdio", False, f"{type(e).__name__}: {e}")
        return False

    check("Server starts and lists its tools", len(tools) == 5, ", ".join(tools))
    check("A tool call reaches Moodle", userid.isdigit(), f"user id {userid}")
    return True


# ------------------------------------------------------- message handling
def check_message_formatting():
    section("4. Message handling (offline, with sample data)")
    from moodle_client import MoodleClient

    cases = {
        "unread conversation with no message body": (
            [{"isread": False, "unreadcount": 1,
              "members": [{"fullname": "Ann"}], "messages": []}],
            lambda out: "Ann" in out and "unavailable" in out,
        ),
        "conversation with an empty member list": (
            [{"isread": False, "unreadcount": 1, "members": [],
              "messages": [{"text": "hi", "timecreated": 1755000000}]}],
            lambda out: "Unknown" in out,
        ),
        "timestamp does not leak between conversations": (
            [{"isread": False, "unreadcount": 1, "members": [{"fullname": "A"}],
              "messages": [{"text": "old", "timecreated": 1700000000}]},
             {"isread": False, "unreadcount": 1, "members": [{"fullname": "B"}],
              "messages": []}],
            lambda out: out.count("2023-11-15") == 1,
        ),
        "HTML entities are decoded": (
            [{"isread": False, "unreadcount": 1, "members": [{"fullname": "C"}],
              "messages": [{"text": "<p>A &amp; B</p>", "timecreated": 1755000000}]}],
            lambda out: "A & B" in out,
        ),
    }

    original = MoodleClient.call
    ok = True
    try:
        for label, (conversations, verify) in cases.items():
            async def fake(self, wsfunction, _c=conversations, **params):
                if wsfunction == "core_webservice_get_site_info":
                    return {"userid": 1}
                if wsfunction == "core_message_get_conversations":
                    return {"conversations": _c}
                return None

            MoodleClient.call = fake
            client = MoodleClient("https://example.invalid", "token")
            try:
                out = asyncio.run(client.check_new_messages())
                ok &= check(label, verify(out), out.replace("\n", " | ")[:70])
            except Exception as e:
                ok &= check(label, False, f"{type(e).__name__}: {e}")
    finally:
        MoodleClient.call = original
    return ok


# ---------------------------------------------------------- user isolation
def check_isolation():
    section("5. Keeping users apart (offline, with sample data)")
    from moodle_client import MoodleClient

    people = {
        "token_a": {"userid": 101, "name": "Course A"},
        "token_b": {"userid": 202, "name": "Course B"},
    }

    original = MoodleClient.call

    async def fake(self, wsfunction, **params):
        who = people[self.token]
        if wsfunction == "core_webservice_get_site_info":
            return {"userid": who["userid"]}
        if wsfunction == "core_enrol_get_users_courses":
            assert params.get("userid") == who["userid"], "wrong user id sent"
            return [{"id": 1, "fullname": who["name"]}]
        return None

    MoodleClient.call = fake
    try:
        async def run():
            clients = [MoodleClient("https://example.invalid", t)
                       for t in ("token_a", "token_b")] * 10
            results = await asyncio.gather(*(c.get_courses() for c in clients))
            return list(zip(clients, results))

        pairs = asyncio.run(run())
        mixed = [
            c.token for c, out in pairs
            if people[c.token]["name"] not in out
        ]
        ok = check("20 concurrent requests each get their own data",
                   not mixed, "no cross-over" if not mixed else f"leaked: {mixed}")
    except Exception as e:
        ok = check("20 concurrent requests each get their own data", False,
                   f"{type(e).__name__}: {e}")
    finally:
        MoodleClient.call = original

    for args in [("https://example.invalid", ""), ("", "token")]:
        try:
            MoodleClient(*args)
            ok &= check(f"rejects {args}", False, "it was accepted")
        except ValueError:
            ok &= check(f"rejects incomplete settings {args}", True)
    return ok


# --------------------------------------------------------- remote + oauth
def check_remote_oauth():
    section("6. Remote server and OAuth (what Claude does)")
    import httpx
    import uvicorn

    import remote_server

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    app = remote_server.build_app(base)
    config = uvicorn.Config(app, host="127.0.0.1", port=port,
                            log_level="error", access_log=False)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(80):
        if server.started:
            break
        time.sleep(0.2)
    if not server.started:
        return check("Remote server starts", False, "it did not come up")

    ok = True
    try:
        # -- discovery
        meta = httpx.get(f"{base}/.well-known/oauth-authorization-server", timeout=15)
        ok &= check("Publishes the authorization server metadata",
                    meta.status_code == 200)
        res_meta = httpx.get(f"{base}/.well-known/oauth-protected-resource", timeout=15)
        ok &= check("Publishes the protected resource metadata",
                    res_meta.status_code == 200)

        # -- unauthenticated access is refused and points at the login
        anon = httpx.post(
            f"{base}/mcp", timeout=15, follow_redirects=False,
            headers={"Accept": "application/json, text/event-stream",
                     "Content-Type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                             "clientInfo": {"name": "selftest", "version": "1"}}},
        )
        ok &= check("Refuses anonymous access with 401",
                    anon.status_code == 401, f"HTTP {anon.status_code}")
        ok &= check("Tells the client where to sign in",
                    "www-authenticate" in anon.headers)

        # -- registration, as Claude does automatically
        reg = httpx.post(f"{base}/register", timeout=15, json={
            "client_name": "selftest",
            "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none", "scope": "moodle",
        })
        ok &= check("Accepts client registration",
                    reg.status_code in (200, 201), f"HTTP {reg.status_code}")
        if reg.status_code not in (200, 201):
            return ok
        client_id = reg.json()["client_id"]

        # -- authorization redirects to our sign-in page
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        auth = httpx.get(f"{base}/authorize", timeout=15, follow_redirects=False, params={
            "response_type": "code", "client_id": client_id,
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "state": "selftest", "code_challenge": challenge,
            "code_challenge_method": "S256", "scope": "moodle",
        })
        location = auth.headers.get("location", "")
        ok &= check("Sends the user to the sign-in page",
                    auth.status_code in (302, 307) and "/login" in location)
        key = location.split("k=")[1].split("&")[0] if "k=" in location else ""

        page = httpx.get(f"{base}/login", params={"k": key}, timeout=15)
        ok &= check("Sign-in page renders", page.status_code == 200)
        ok &= check("Sign-in page works on a phone screen", "viewport" in page.text)
        ok &= check("Sign-in page asks for a username and password",
                    'name="username"' in page.text and 'type="password"' in page.text)

        expired = httpx.get(f"{base}/login", params={"k": "not-a-real-key"}, timeout=15)
        ok &= check("Rejects an expired or forged sign-in link",
                    expired.status_code == 400)

        # -- issue a token the way a successful sign-in would
        redirect = remote_server._provider.complete_login(key, os.getenv("MOODLE_TOKEN"))
        code = redirect.split("code=")[1].split("&")[0]
        tok = httpx.post(f"{base}/token", timeout=15, data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "client_id": client_id, "code_verifier": verifier,
        })
        ok &= check("Exchanges the code for an access token", tok.status_code == 200)
        if tok.status_code != 200:
            return ok
        tokens = tok.json()
        ok &= check("The Moodle token is not readable inside it",
                    os.getenv("MOODLE_TOKEN") not in tokens["access_token"])

        reused = httpx.post(f"{base}/token", timeout=15, data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "client_id": client_id, "code_verifier": verifier,
        })
        ok &= check("Refuses to reuse an authorization code",
                    reused.status_code >= 400, f"HTTP {reused.status_code}")

        # -- a real tool call over HTTP
        def call(access_token, method, params=None):
            r = httpx.post(f"{base}/mcp", timeout=60, follow_redirects=False,
                           headers={"Authorization": f"Bearer {access_token}",
                                    "Accept": "application/json, text/event-stream",
                                    "Content-Type": "application/json"},
                           json={"jsonrpc": "2.0", "id": 1,
                                 "method": method, "params": params or {}})
            if r.status_code != 200:
                return {"_status": r.status_code}
            for line in r.text.splitlines():
                if line.startswith("data: "):
                    return json.loads(line[6:])
            return {}

        access = tokens["access_token"]
        call(access, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                    "clientInfo": {"name": "selftest", "version": "1"}})
        listed = call(access, "tools/list")
        names = [t["name"] for t in listed.get("result", {}).get("tools", [])]
        ok &= check("Lists tools once signed in", len(names) == 5, ", ".join(names))

        called = call(access, "tools/call",
                      {"name": "get_my_userid", "arguments": {}})
        text = "".join(c.get("text", "")
                       for c in called.get("result", {}).get("content", []))
        ok &= check("A signed-in tool call reaches Moodle",
                    text.strip().isdigit(), f"user id {text.strip()}")

        # -- forged and swapped tokens
        for bad, label in [
            ("not-a-token", "random string"),
            (access[:-6] + "AAAAAA", "tampered access token"),
            (tokens.get("refresh_token", "x"), "refresh token used as an access token"),
        ]:
            r = httpx.post(f"{base}/mcp", timeout=20, follow_redirects=False,
                           headers={"Authorization": f"Bearer {bad}",
                                    "Accept": "application/json, text/event-stream",
                                    "Content-Type": "application/json"},
                           json={"jsonrpc": "2.0", "id": 1,
                                 "method": "tools/list", "params": {}})
            ok &= check(f"Rejects a {label}", r.status_code == 401,
                        f"HTTP {r.status_code}")

        # -- refresh keeps working
        refreshed = httpx.post(f"{base}/token", timeout=15, data={
            "grant_type": "refresh_token",
            "refresh_token": tokens.get("refresh_token", ""),
            "client_id": client_id, "scope": "moodle",
        })
        ok &= check("Refreshing gives a new access token",
                    refreshed.status_code == 200, f"HTTP {refreshed.status_code}")
    finally:
        server.should_exit = True
    return ok


MANUAL_STEPS = """
Steps that still need a person and a browser
--------------------------------------------
These cannot be automated, because they involve a real Claude account.

  1. Start the server:            ./start-server.command
     Note the URL it prints, e.g. https://xxxx.trycloudflare.com/mcp

  2. In a browser, open https://claude.ai and go to
     Settings > Connectors > Add custom connector.
     Paste the URL and add it.

  3. Claude opens the Moodle sign-in page. Sign in.
     -> If your password is rejected, check it works on the Moodle website.

  4. Start a new chat and ask: "Do I have any new messages?"
     Claude should call check_new_messages and answer from the result.

  5. Open the Claude app on a phone and ask the same question.
     The connector should already be there.

  6. If a second Moodle account is available, connect it from another
     Claude account and confirm each one only sees its own data.
"""


def main():
    parser = argparse.ArgumentParser(description="Self-test for the Moodle MCP server")
    parser.add_argument("--offline", action="store_true",
                        help="skip every check that needs the network")
    args = parser.parse_args()

    print("Moodle MCP server self-test")

    settings_ok = check_settings()

    if args.offline:
        section("2-3, 6. Network checks")
        skip("Moodle connection, local MCP server, remote server and OAuth",
             "--offline was given")
    elif not settings_ok:
        section("2-3, 6. Network checks")
        skip("Moodle connection, local MCP server, remote server and OAuth",
             "settings are incomplete; run setup_gui.py first")
    else:
        check_moodle()
        check_local_mcp()

    check_message_formatting()
    check_isolation()

    if not args.offline and settings_ok:
        check_remote_oauth()

    section("Result")
    print(f"  passed:  {len(PASSED)}")
    print(f"  failed:  {len(FAILED)}")
    print(f"  skipped: {len(SKIPPED)}")
    if FAILED:
        print()
        print("  Failed checks:")
        for name in FAILED:
            print(f"    - {name}")

    print(MANUAL_STEPS)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
