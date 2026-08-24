"""Moodle のトークン取得・検証と .env の読み書きをまとめたモジュール。

setup_gui.py（GUI ウィザード）と get_token.py（CLI）の両方から使う。
Cloudflare で保護された Moodle でも、ブラウザの TLS フィンガープリントを
偽装することで token.php / webservice を叩ける。
"""
import os
import re

from curl_cffi import requests

IMPERSONATE = os.getenv("MOODLE_IMPERSONATE", "chrome131")
SERVICE = "moodle_mobile_app"
DEFAULT_URL = "https://lms.fcpc.edu.ph"
ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(ROOT, ".env")

# Moodle が返すエラーコードを、素人にも分かる日本語に翻訳する
ERROR_MESSAGES = {
    "invalidlogin": (
        "ユーザー名またはパスワードが違います。\n"
        "Moodle にブラウザでログインするときと同じものを入力してください。"
    ),
    "enablewsdescription": (
        "この Moodle サイトではウェブサービスが無効になっています。\n"
        "サイト管理者に「モバイルアプリ用のウェブサービスを有効にしてほしい」と依頼してください。"
    ),
    "usernotconfirmed": "アカウントがまだ確認済みになっていません。確認メールのリンクを開いてください。",
    "sitemaintenance": "Moodle サイトが現在メンテナンス中です。しばらく待ってから再度お試しください。",
    "forcepasswordchangenotice": (
        "パスワードの変更を求められています。\n"
        "先にブラウザで Moodle にログインしてパスワードを変更してください。"
    ),
    "potentialidporsso": (
        "このアカウントは外部ログイン（Google ログインなど）を使っている可能性があります。\n"
        "Moodle 本体のユーザー名とパスワードが必要です。"
    ),
}


class MoodleAuthError(Exception):
    """利用者にそのまま見せられる日本語メッセージを持つ例外。"""


def normalize_url(base_url: str) -> str:
    """入力された URL を整形する。https:// の付け忘れや末尾スラッシュを許容する。"""
    url = (base_url or "").strip()
    if not url:
        raise MoodleAuthError("Moodle の URL を入力してください。")
    if not re.match(r"^https?://", url):
        url = "https://" + url
    # 「.../login/index.php」などを貼り付けられても大丈夫にする
    url = re.sub(r"/(login|my|course)(/.*)?$", "", url.rstrip("/"))
    return url.rstrip("/")


def _get(url: str, params: dict):
    try:
        return requests.get(url, params=params, impersonate=IMPERSONATE, timeout=30)
    except Exception as e:
        raise MoodleAuthError(
            "Moodle に接続できませんでした。\n"
            "・インターネットに繋がっているか\n"
            "・URL が正しいか（例: https://lms.fcpc.edu.ph）\n"
            "を確認してください。\n\n"
            f"詳細: {e}"
        )


def _parse_json(response, url: str):
    if response.status_code != 200:
        raise MoodleAuthError(
            f"Moodle が エラー {response.status_code} を返しました。\n"
            f"URL が正しいか確認してください。\n\n詳細: {response.text[:200]}"
        )
    try:
        return response.json()
    except Exception:
        raise MoodleAuthError(
            "Moodle から想定外の応答が返りました（JSON ではありません）。\n"
            "セキュリティ機能（Cloudflare）に遮断された可能性があります。\n"
            "少し時間を置いてから再度お試しください。\n\n"
            f"詳細: {response.text[:200]}"
        )


def fetch_token(base_url: str, username: str, password: str) -> str:
    """ユーザー名とパスワードからウェブサービストークンを取得する。"""
    base_url = normalize_url(base_url)
    if not username.strip():
        raise MoodleAuthError("ユーザー名を入力してください。")
    if not password:
        raise MoodleAuthError("パスワードを入力してください。")

    url = f"{base_url}/login/token.php"
    r = _get(url, {"username": username.strip(), "password": password, "service": SERVICE})
    data = _parse_json(r, url)

    if isinstance(data, dict) and data.get("token"):
        return data["token"]

    code = (data or {}).get("errorcode", "")
    if code in ERROR_MESSAGES:
        raise MoodleAuthError(ERROR_MESSAGES[code])
    raise MoodleAuthError(
        "トークンを取得できませんでした。\n\n"
        f"Moodle からの応答: {(data or {}).get('error') or data}"
    )


def verify_token(base_url: str, token: str) -> dict:
    """トークンが本当に使えるか確認し、サイト情報を返す。"""
    base_url = normalize_url(base_url)
    url = f"{base_url}/webservice/rest/server.php"
    r = _get(
        url,
        {
            "wstoken": token,
            "moodlewsrestformat": "json",
            "wsfunction": "core_webservice_get_site_info",
        },
    )
    data = _parse_json(r, url)

    if isinstance(data, dict) and data.get("exception"):
        code = data.get("errorcode", "")
        if code == "invalidtoken":
            raise MoodleAuthError(
                "トークンが無効か、有効期限が切れています。\n"
                "セットアップをやり直してトークンを取り直してください。"
            )
        raise MoodleAuthError(f"Moodle エラー [{code}]: {data.get('message')}")

    if not isinstance(data, dict) or "userid" not in data:
        raise MoodleAuthError(f"サイト情報を取得できませんでした。\n\n詳細: {str(data)[:200]}")
    return data


def read_env() -> dict:
    """.env を読み込んで辞書で返す（無ければ空）。"""
    values = {}
    if not os.path.exists(ENV_PATH):
        return values
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def update_env(values: dict) -> str:
    """.env の指定キーを更新（無ければ追記）。コメントや他の行はそのまま残す。"""
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            lines = f.read().splitlines()

    for key, value in values.items():
        if value is None:
            continue
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
        newline = f'{key}="{value}"'
        for i, ln in enumerate(lines):
            if pattern.match(ln):
                lines[i] = newline
                break
        else:
            lines.append(newline)

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")
    return ENV_PATH
