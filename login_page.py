"""The Moodle sign-in page that Claude opens during the OAuth flow.

Most students will see this on a phone, so the page stays deliberately plain.
The password is used once to obtain a token and is never stored or logged.

There are two ways to sign in. Normally a student enters their Moodle username
and password. On sites where students authenticate through Google or another
identity provider they have no Moodle password, so the page also accepts a
web service token directly - either the plain token or the whole
`moodlemobile://token=...` value that admin/tool/mobile/launch.php returns.
"""
import base64
import html as html_mod

from starlette.responses import HTMLResponse, RedirectResponse

import moodle_auth
from moodle_auth import MoodleAuthError

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in to Moodle</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    margin: 0; padding: 24px; line-height: 1.6;
    background: #f6f7f9; color: #1a1a1a;
  }}
  .card {{
    max-width: 420px; margin: 0 auto; background: #fff;
    border-radius: 14px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,.12);
  }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  p.sub {{ margin: 0 0 20px; color: #555; font-size: 14px; }}
  label {{ display: block; font-size: 14px; font-weight: 600; margin: 14px 0 6px; }}
  input {{
    width: 100%; padding: 12px; font-size: 16px;
    border: 1px solid #c6c8cc; border-radius: 8px; background: #fff; color: inherit;
  }}
  button {{
    width: 100%; margin-top: 20px; padding: 13px; font-size: 16px; font-weight: 600;
    background: #2d6cdf; color: #fff; border: 0; border-radius: 8px; cursor: pointer;
  }}
  .err {{
    background: #fdecea; border: 1px solid #f5c2bd; color: #9d261b;
    padding: 12px; border-radius: 8px; font-size: 14px; margin-bottom: 16px;
    white-space: pre-wrap;
  }}
  .note {{ margin-top: 18px; color: #666; font-size: 12.5px; }}
  .or {{
    display: flex; align-items: center; gap: 10px;
    margin: 24px 0 2px; color: #8a8f96; font-size: 12.5px;
  }}
  .or::before, .or::after {{ content: ""; flex: 1; height: 1px; background: #dcdee1; }}
  button.alt {{ background: #5a6270; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #16181c; color: #e8e8e8; }}
    .card {{ background: #212429; box-shadow: none; }}
    input {{ background: #2a2e35; border-color: #3a3f47; }}
    p.sub, .note, .or {{ color: #a0a4ab; }}
    .or::before, .or::after {{ background: #3a3f47; }}
  }}
</style>
</head>
<body>
  <div class="card">
    <h1>Sign in to Moodle</h1>
    <p class="sub">This lets Claude look up your own assignments and messages.</p>
    {error}
    <form method="post" action="/login">
      <input type="hidden" name="k" value="{key}">
      <label for="u">Username</label>
      <input id="u" name="username" autocapitalize="none" autocorrect="off"
             autocomplete="username" required>
      <label for="p">Password</label>
      <input id="p" name="password" type="password" autocomplete="current-password" required>
      <button type="submit">Sign in and allow</button>
    </form>
    <p class="note">
      Use the same username and password you use for Moodle.<br>
      Your password is used once to sign in and is never stored.
    </p>

    <div class="or">or use a token</div>
    <form method="post" action="/login">
      <input type="hidden" name="k" value="{key}">
      <label for="t">Moodle web service token</label>
      <input id="t" name="token" autocapitalize="none" autocorrect="off"
             spellcheck="false" placeholder="32-character token" required>
      <button class="alt" type="submit">Continue with token</button>
    </form>
    <p class="note">
      For accounts that sign in through Google and have no Moodle password.
      Pasting the whole <code>moodlemobile://token=...</code> value works too.
    </p>
  </div>
</body>
</html>
"""

EXPIRED = (
    "<p style=\"font-family:sans-serif;padding:24px\">"
    "This page has expired. Please connect again from Claude.</p>"
)


def extract_token(raw: str) -> str:
    """Pull a web service token out of whatever the student pasted.

    Accepts the plain token, `moodlemobile://token=<base64>` as returned by
    admin/tool/mobile/launch.php, or just the base64 part of it. Anything that
    is not recognisably a launch.php value is handed back unchanged, so an
    ordinary token still works.
    """
    raw = (raw or "").strip()
    if "token=" in raw:
        raw = raw.split("token=", 1)[1]
    raw = raw.strip().strip("/")
    if not raw:
        return ""

    # launch.php returns base64 of "siteid:::wstoken[:::privatetoken]".
    try:
        decoded = base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    except Exception:
        return raw
    parts = decoded.split(":::")
    return parts[1].strip() if len(parts) >= 2 and parts[1].strip() else raw


def render(key: str, error: str = "") -> HTMLResponse:
    block = f'<div class="err">{html_mod.escape(error)}</div>' if error else ""
    return HTMLResponse(PAGE.format(key=html_mod.escape(key), error=block))


def make_routes(provider, moodle_url: str):
    """Build the GET and POST handlers for the sign-in page."""

    async def get_login(request):
        key = request.query_params.get("k", "")
        if not provider.get_pending(key):
            return HTMLResponse(EXPIRED, status_code=400)
        return render(key)

    async def post_login(request):
        form = await request.form()
        key = str(form.get("k", ""))
        if not provider.get_pending(key):
            return HTMLResponse(EXPIRED, status_code=400)

        pasted = extract_token(str(form.get("token", "")))
        try:
            if pasted:
                # The token route skips login/token.php entirely, which is the
                # point: SSO accounts have no password to send there.
                token = pasted
            else:
                token = moodle_auth.fetch_token(
                    moodle_url,
                    str(form.get("username", "")),
                    str(form.get("password", "")),
                )
            moodle_auth.verify_token(moodle_url, token)
        except MoodleAuthError as e:
            return render(key, str(e))

        redirect_to = provider.complete_login(key, token)
        if not redirect_to:
            return HTMLResponse(EXPIRED, status_code=400)
        return RedirectResponse(redirect_to, status_code=302)

    return get_login, post_login
