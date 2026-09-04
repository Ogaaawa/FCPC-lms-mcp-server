"""Moodle token retrieval and .env handling.

Used by the setup wizard (setup_gui.py), the command line helper
(get_token.py) and the OAuth login page (login_page.py).

Moodle sites behind Cloudflare reject ordinary HTTPS clients, so requests
here go through curl_cffi with a browser TLS fingerprint.
"""
import os
import re

from curl_cffi import requests

IMPERSONATE = os.getenv("MOODLE_IMPERSONATE", "chrome131")

# Which external service login/token.php issues a token for. The default is
# Moodle's built-in mobile service, which exposes every function the site has.
# A site that has defined a restricted service for this assistant should name
# it here instead, so the token cannot reach beyond the functions it needs.
SERVICE = os.getenv("MOODLE_SERVICE", "moodle_mobile_app")
DEFAULT_URL = "https://lms.fcpc.edu.ph"
ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(ROOT, ".env")

# Moodle error codes translated into something a student can act on.
ERROR_MESSAGES = {
    "invalidlogin": (
        "Wrong username or password.\n"
        "Use the same details you use to log in to Moodle in a browser."
    ),
    "enablewsdescription": (
        "Web services are turned off on this Moodle site.\n"
        "Ask your Moodle administrator to enable the mobile app web service."
    ),
    "usernotconfirmed": (
        "Your account has not been confirmed yet.\n"
        "Open the confirmation link in the email Moodle sent you."
    ),
    "sitemaintenance": (
        "The Moodle site is in maintenance mode. Please try again later."
    ),
    "forcepasswordchangenotice": (
        "Moodle is asking you to change your password.\n"
        "Log in to Moodle in a browser and change it first."
    ),
    "potentialidporsso": (
        "This account appears to sign in through an external provider "
        "(for example Google).\n"
        "You need a Moodle username and password to continue."
    ),
}


class MoodleAuthError(Exception):
    """Carries a message that can be shown to the user as-is."""


def normalize_url(base_url: str) -> str:
    """Tidy up a site address: add https://, drop trailing paths and slashes."""
    url = (base_url or "").strip()
    if not url:
        raise MoodleAuthError("Please enter your Moodle address.")
    if not re.match(r"^https?://", url):
        url = "https://" + url
    # Tolerate someone pasting ".../login/index.php" or a course URL.
    url = re.sub(r"/(login|my|course)(/.*)?$", "", url.rstrip("/"))
    return url.rstrip("/")


def _get(url: str, params: dict):
    try:
        return requests.get(url, params=params, impersonate=IMPERSONATE, timeout=30)
    except Exception as e:
        raise MoodleAuthError(
            "Could not reach Moodle.\n"
            "Check that you are online and that the address is correct "
            "(for example https://lms.fcpc.edu.ph).\n\n"
            f"Details: {e}"
        )


def _parse_json(response, url: str):
    if response.status_code != 200:
        raise MoodleAuthError(
            f"Moodle returned error {response.status_code}.\n"
            f"Check that the address is correct.\n\nDetails: {response.text[:200]}"
        )
    try:
        return response.json()
    except Exception:
        raise MoodleAuthError(
            "Moodle returned an unexpected response (not JSON).\n"
            "It may have been blocked by the site's security layer. "
            "Please wait a moment and try again.\n\n"
            f"Details: {response.text[:200]}"
        )


def fetch_token(base_url: str, username: str, password: str,
                service: str = "") -> str:
    """Exchange a username and password for a web service token.

    `service` is the external service shortname; it falls back to whatever
    MOODLE_SERVICE says, and then to Moodle's mobile service.
    """
    base_url = normalize_url(base_url)
    if not username.strip():
        raise MoodleAuthError("Please enter your username.")
    if not password:
        raise MoodleAuthError("Please enter your password.")

    url = f"{base_url}/login/token.php"
    r = _get(url, {"username": username.strip(), "password": password,
                   "service": service or SERVICE})
    data = _parse_json(r, url)

    if isinstance(data, dict) and data.get("token"):
        return data["token"]

    code = (data or {}).get("errorcode", "")
    if code in ERROR_MESSAGES:
        raise MoodleAuthError(ERROR_MESSAGES[code])
    raise MoodleAuthError(
        "Could not get a token.\n\n"
        f"Moodle said: {(data or {}).get('error') or data}"
    )


def verify_token(base_url: str, token: str) -> dict:
    """Check that a token works and return the site information."""
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
                "That token is invalid or has expired.\n"
                "Run setup again to get a new one."
            )
        raise MoodleAuthError(f"Moodle error [{code}]: {data.get('message')}")

    if not isinstance(data, dict) or "userid" not in data:
        raise MoodleAuthError(
            f"Could not read the site information.\n\nDetails: {str(data)[:200]}"
        )
    return data


def read_env() -> dict:
    """Read .env into a dict. Returns an empty dict if there is no file."""
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
    """Update the given keys in .env, keeping comments and other lines intact."""
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            lines = f.read().splitlines()
    else:
        # First run: start from .env.example so the comments carry over.
        example = os.path.join(os.path.dirname(ENV_PATH), ".env.example")
        if os.path.exists(example):
            with open(example, encoding="utf-8") as f:
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


def connector_url(base_url: str) -> str:
    """Build the URL students paste into Claude's custom connector dialog.

    The URL is the same for everyone; users are told apart by the OAuth login.
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return ""
    if not re.match(r"^https?://", base):
        base = "https://" + base
    base = re.sub(r"/mcp/?$", "", base).rstrip("/")
    return f"{base}/mcp"
