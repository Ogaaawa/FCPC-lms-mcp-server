"""Fetch a Moodle web service token and save it to .env (command line).

The graphical wizard is easier if you can run it:
    python setup_gui.py      (or double-click setup.command / setup.bat)

Usage:
    python get_token.py
      -> prompts for the address, username and password
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
        base_url = input(f"Moodle address [{moodle_auth.DEFAULT_URL}]: ").strip() or moodle_auth.DEFAULT_URL
        username = input("Username: ").strip()
        password = getpass("Password (not shown as you type): ")

    try:
        base_url = moodle_auth.normalize_url(base_url)
        print(f"\nConnecting to {base_url} ...")
        token = moodle_auth.fetch_token(base_url, username, password)
        print("Got a token.")

        info = moodle_auth.verify_token(base_url, token)
        print(f"Site: {info.get('sitename')}")
        print(f"Signed in as: {info.get('fullname')} ({info.get('username')})")

        path = moodle_auth.update_env({"MOODLE_URL": base_url, "MOODLE_TOKEN": token})
        print(f"\nSaved settings to {path}")
        print("You can now run: python client.py server.py")
    except MoodleAuthError as e:
        print(f"\n{e}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
