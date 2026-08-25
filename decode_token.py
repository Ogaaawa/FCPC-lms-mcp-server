"""Decode the base64 token returned by Moodle mobile launch.php.

Users who sign in through SSO (Google and similar) cannot use
login/token.php, so they go through admin/tool/mobile/launch.php the same way
the official mobile app does. That returns `moodlemobile://token=<base64>`;
pass the <base64> part to this script.

Usage:
    python decode_token.py <base64 string>
    python decode_token.py            # prompts for it
"""
import base64
import sys

import moodle_auth
from moodle_auth import MoodleAuthError


def decode(raw: str) -> str:
    raw = raw.strip()
    # Strip the URL prefix if it was pasted in.
    if "token=" in raw:
        raw = raw.split("token=", 1)[1]
    raw = raw.strip().strip("/")
    # Restore base64 padding.
    raw += "=" * (-len(raw) % 4)
    try:
        decoded = base64.b64decode(raw).decode("utf-8", errors="replace")
    except Exception as e:
        raise SystemExit(f"Could not decode that as base64: {e}")
    parts = decoded.split(":::")
    if len(parts) < 2:
        raise SystemExit(f"Unexpected format: {decoded!r}")
    # parts[0]=signature, parts[1]=wstoken, parts[2]=privatetoken (if present)
    return parts[1]


def main():
    base_url = moodle_auth.read_env().get("MOODLE_URL") or moodle_auth.DEFAULT_URL

    if len(sys.argv) >= 2:
        raw = sys.argv[1]
    else:
        raw = input("Paste everything after token= in moodlemobile://token=... : ")

    token = decode(raw)
    print(f"\nExtracted wstoken: {token}")

    try:
        info = moodle_auth.verify_token(base_url, token)
        print(f"Site: {info.get('sitename')}")
        print(f"Signed in as: {info.get('fullname')} ({info.get('username')})")
    except MoodleAuthError as e:
        print(f"\n{e}", file=sys.stderr)
        raise SystemExit(1)

    path = moodle_auth.update_env({"MOODLE_URL": base_url, "MOODLE_TOKEN": token})
    print(f"\nSaved settings to {path}")
    print("You can now run: python client.py server.py")


if __name__ == "__main__":
    main()
