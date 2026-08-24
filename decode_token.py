"""Moodle モバイル launch.php が返す base64 トークンをデコードして .env に保存する。

SSO(Google など)でログインしているユーザーは login/token.php を使えないため、
公式モバイルアプリと同じ admin/tool/mobile/launch.php フローでトークンを得る。
その結果は `moodlemobile://token=<base64>` の形で返るので、
その <base64> 部分をこのスクリプトに渡す。

使い方:
    python decode_token.py <base64文字列>
    python decode_token.py            # 対話入力
"""
import base64
import sys

import moodle_auth
from moodle_auth import MoodleAuthError


def decode(raw: str) -> str:
    raw = raw.strip()
    # URL に付いていた前置きを掃除
    if "token=" in raw:
        raw = raw.split("token=", 1)[1]
    raw = raw.strip().strip("/")
    # base64 のパディング補正
    raw += "=" * (-len(raw) % 4)
    try:
        decoded = base64.b64decode(raw).decode("utf-8", errors="replace")
    except Exception as e:
        raise SystemExit(f"base64 として読み取れませんでした: {e}")
    parts = decoded.split(":::")
    if len(parts) < 2:
        raise SystemExit(f"想定外の形式です: {decoded!r}")
    # parts[0]=署名, parts[1]=wstoken, parts[2]=privatetoken(あれば)
    return parts[1]


def main():
    base_url = moodle_auth.read_env().get("MOODLE_URL") or moodle_auth.DEFAULT_URL

    if len(sys.argv) >= 2:
        raw = sys.argv[1]
    else:
        raw = input("moodlemobile://token=... の token= 以降を貼り付け: ")

    token = decode(raw)
    print(f"\n取り出した wstoken: {token}")

    try:
        info = moodle_auth.verify_token(base_url, token)
        print(f"サイト: {info.get('sitename')}")
        print(f"ログイン中: {info.get('fullname')} ({info.get('username')})")
    except MoodleAuthError as e:
        print(f"\n{e}", file=sys.stderr)
        raise SystemExit(1)

    path = moodle_auth.update_env({"MOODLE_URL": base_url, "MOODLE_TOKEN": token})
    print(f"\n設定を保存しました -> {path}")
    print("これで `python client.py server.py` が使えます。")


if __name__ == "__main__":
    main()
