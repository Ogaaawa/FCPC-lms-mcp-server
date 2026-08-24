"""Claude から開かれる Moodle ログイン画面。

スマートフォンのブラウザで表示される前提なので、余計な要素を置かない。
入力されたパスワードはトークン取得に一度使うだけで、保存も記録もしない。
"""
import html as html_mod

from starlette.responses import HTMLResponse, RedirectResponse

import moodle_auth
from moodle_auth import MoodleAuthError

PAGE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Moodle にログイン</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", sans-serif;
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
  @media (prefers-color-scheme: dark) {{
    body {{ background: #16181c; color: #e8e8e8; }}
    .card {{ background: #212429; box-shadow: none; }}
    input {{ background: #2a2e35; border-color: #3a3f47; }}
    p.sub, .note {{ color: #a0a4ab; }}
  }}
</style>
</head>
<body>
  <div class="card">
    <h1>Moodle にログイン</h1>
    <p class="sub">Claude から自分の課題やメッセージを見られるようにします。</p>
    {error}
    <form method="post" action="/login">
      <input type="hidden" name="k" value="{key}">
      <label for="u">ユーザー名</label>
      <input id="u" name="username" autocapitalize="none" autocorrect="off"
             autocomplete="username" required>
      <label for="p">パスワード</label>
      <input id="p" name="password" type="password" autocomplete="current-password" required>
      <button type="submit">ログインして許可する</button>
    </form>
    <p class="note">
      Moodle にログインするときと同じユーザー名・パスワードです。<br>
      パスワードはこの場で1度使うだけで、保存されません。
    </p>
  </div>
</body>
</html>
"""


def render(key: str, error: str = "") -> HTMLResponse:
    block = f'<div class="err">{html_mod.escape(error)}</div>' if error else ""
    return HTMLResponse(PAGE.format(key=html_mod.escape(key), error=block))


def make_routes(provider, moodle_url: str):
    """ログイン画面の GET / POST ハンドラを作る。"""

    async def get_login(request):
        key = request.query_params.get("k", "")
        if not provider.get_pending(key):
            return HTMLResponse(
                "<p>この画面は期限切れです。Claude でもう一度接続してください。</p>",
                status_code=400,
            )
        return render(key)

    async def post_login(request):
        form = await request.form()
        key = str(form.get("k", ""))
        if not provider.get_pending(key):
            return HTMLResponse(
                "<p>この画面は期限切れです。Claude でもう一度接続してください。</p>",
                status_code=400,
            )

        try:
            token = moodle_auth.fetch_token(
                moodle_url, str(form.get("username", "")), str(form.get("password", ""))
            )
            moodle_auth.verify_token(moodle_url, token)
        except MoodleAuthError as e:
            return render(key, str(e))

        redirect_to = provider.complete_login(key, token)
        if not redirect_to:
            return HTMLResponse("<p>接続に失敗しました。やり直してください。</p>", status_code=400)
        return RedirectResponse(redirect_to, status_code=302)

    return get_login, post_login
