"""Moodle のウェブサービストークンを取得して .env に書き込む（コマンドライン版）。

画面つきのセットアップが使える場合は setup_gui.py の方が簡単:
    python setup_gui.py
    （macOS なら「セットアップ.command」をダブルクリック）

使い方:
    python get_token.py
      -> URL / ユーザー名 / パスワードを対話入力
    python get_token.py https://lms.fcpc.edu.ph <username> <password>
"""
import sys
from getpass import getpass

import moodle_auth
from moodle_auth import MoodleAuthError


def main():
    if len(sys.argv) >= 4:
        base_url, username, password = sys.argv[1], sys.argv[2], sys.argv[3]
    else:
        base_url = input(f"Moodle URL [{moodle_auth.DEFAULT_URL}]: ").strip() or moodle_auth.DEFAULT_URL
        username = input("ユーザー名: ").strip()
        password = getpass("パスワード（入力しても画面には出ません）: ")

    try:
        base_url = moodle_auth.normalize_url(base_url)
        print(f"\n{base_url} に接続しています...")
        token = moodle_auth.fetch_token(base_url, username, password)
        print("トークンを取得しました。")

        info = moodle_auth.verify_token(base_url, token)
        print(f"サイト: {info.get('sitename')}")
        print(f"ログイン中: {info.get('fullname')} ({info.get('username')})")

        path = moodle_auth.update_env({"MOODLE_URL": base_url, "MOODLE_TOKEN": token})
        print(f"\n設定を保存しました -> {path}")
        print("これで `python client.py server.py` が使えます。")
    except MoodleAuthError as e:
        print(f"\n{e}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
