"""OAuth authorization server, so registering the connector is just one URL.

Every student registers the same URL. Claude then opens the Moodle sign-in
page by itself, and signing in issues an access token for that person. The
whole flow works in a phone browser.

Moodle tokens are never stored on the server. Each one is encrypted into the
access token itself and decrypted when needed, which keeps this stateless.
Only the encryption key is kept on disk, in .oauth_key.
"""
import json
import os
import secrets
import time
from urllib.parse import urlencode

from cryptography.fernet import Fernet, InvalidToken
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

ROOT = os.path.dirname(os.path.abspath(__file__))
KEY_PATH = os.path.join(ROOT, ".oauth_key")
CLIENTS_PATH = os.path.join(ROOT, ".oauth_clients.json")

ACCESS_TOKEN_TTL = 60 * 60 * 24 * 30  # 30 days
REFRESH_TOKEN_TTL = 60 * 60 * 24 * 180  # 180 days
CODE_TTL = 300  # authorization codes expire after 5 minutes
SCOPE = "moodle"


def _load_key() -> bytes:
    """Load the encryption key, creating it on first run.

    It is kept on disk so that restarting the server does not sign everyone out.
    """
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, "rb") as f:
            key = f.read().strip()
        if key:
            return key
    key = Fernet.generate_key()
    with open(KEY_PATH, "wb") as f:
        f.write(key)
    os.chmod(KEY_PATH, 0o600)
    return key


class MoodleOAuthProvider(OAuthAuthorizationServerProvider):
    """Treats signing in to Moodle as the OAuth authorization step."""

    def __init__(self, issuer_url: str):
        self.issuer_url = issuer_url.rstrip("/")
        self._fernet = Fernet(_load_key())
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._codes: dict[str, tuple[AuthorizationCode, str]] = {}  # code -> (info, moodle token)
        self._load_clients()

    # --- sealing and unsealing the Moodle token -------------------------
    def seal(self, moodle_token: str, kind: str = "access") -> str:
        """Encrypt a Moodle token into an opaque token string."""
        payload = json.dumps({"t": moodle_token, "k": kind, "iat": int(time.time())}).encode()
        return self._fernet.encrypt(payload).decode()

    def unseal(self, token: str, kind: str = "access") -> str | None:
        """Recover the Moodle token, rejecting a token of the wrong kind."""
        ttl = ACCESS_TOKEN_TTL if kind == "access" else REFRESH_TOKEN_TTL
        try:
            data = json.loads(self._fernet.decrypt(token.encode(), ttl=ttl))
        except (InvalidToken, ValueError):
            return None
        if data.get("k") != kind:
            return None
        return data.get("t")

    # --- client registration (Claude registers itself) ------------------
    def _load_clients(self) -> None:
        if not os.path.exists(CLIENTS_PATH):
            return
        try:
            with open(CLIENTS_PATH, encoding="utf-8") as f:
                raw = json.load(f)
            for cid, info in raw.items():
                self._clients[cid] = OAuthClientInformationFull.model_validate(info)
        except Exception:
            # A corrupt file must not stop startup; Claude re-registers.
            self._clients = {}

    def _save_clients(self) -> None:
        data = {cid: json.loads(c.model_dump_json()) for cid, c in self._clients.items()}
        with open(CLIENTS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.chmod(CLIENTS_PATH, 0o600)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._clients[client_info.client_id] = client_info
        self._save_clients()

    # --- authorization flow ---------------------------------------------
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Return the URL of our own sign-in page."""
        pending = secrets.token_urlsafe(24)
        self._pending = getattr(self, "_pending", {})
        self._purge()
        self._pending[pending] = {
            "client_id": client.client_id,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "code_challenge": params.code_challenge,
            "state": params.state,
            "scopes": params.scopes or [SCOPE],
            "expires_at": time.time() + CODE_TTL,
        }
        return f"{self.issuer_url}/login?{urlencode({'k': pending})}"

    def get_pending(self, key: str) -> dict | None:
        self._purge()
        return getattr(self, "_pending", {}).get(key)

    def complete_login(self, key: str, moodle_token: str) -> str | None:
        """Sign-in succeeded: issue a code and return where to redirect."""
        pending = getattr(self, "_pending", {}).pop(key, None)
        if not pending:
            return None

        code = secrets.token_urlsafe(32)
        self._codes[code] = (
            AuthorizationCode(
                code=code,
                scopes=pending["scopes"],
                expires_at=time.time() + CODE_TTL,
                client_id=pending["client_id"],
                code_challenge=pending["code_challenge"],
                redirect_uri=pending["redirect_uri"],
                redirect_uri_provided_explicitly=pending["redirect_uri_provided_explicitly"],
            ),
            moodle_token,
        )

        query = {"code": code}
        if pending.get("state"):
            query["state"] = pending["state"]
        joiner = "&" if "?" in pending["redirect_uri"] else "?"
        return f"{pending['redirect_uri']}{joiner}{urlencode(query)}"

    def _purge(self) -> None:
        now = time.time()
        pending = getattr(self, "_pending", {})
        for k in [k for k, v in pending.items() if v["expires_at"] < now]:
            pending.pop(k, None)
        for c in [c for c, (info, _) in self._codes.items() if info.expires_at < now]:
            self._codes.pop(c, None)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        self._purge()
        entry = self._codes.get(authorization_code)
        if not entry:
            return None
        info, _ = entry
        return info if info.client_id == client.client_id else None

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        entry = self._codes.pop(authorization_code.code, None)  # single use
        if not entry:
            raise ValueError("Invalid authorization code.")
        _, moodle_token = entry
        return self._issue(moodle_token, authorization_code.scopes)

    async def load_access_token(self, token: str) -> AccessToken | None:
        if self.unseal(token) is None:
            return None
        return AccessToken(
            token=token,
            client_id="moodle",
            scopes=[SCOPE],
            expires_at=None,  # expiry is enforced by the encryption ttl
        )

    def _issue(self, moodle_token: str, scopes: list[str]) -> OAuthToken:
        return OAuthToken(
            access_token=self.seal(moodle_token, "access"),
            token_type="bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=self.seal(moodle_token, "refresh"),
            scope=" ".join(scopes or [SCOPE]),
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        if self.unseal(refresh_token, "refresh") is None:
            return None
        return RefreshToken(
            token=refresh_token, client_id=client.client_id, scopes=[SCOPE], expires_at=None
        )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        moodle_token = self.unseal(refresh_token.token, "refresh")
        if not moodle_token:
            raise ValueError("Invalid refresh token.")
        return self._issue(moodle_token, scopes or [SCOPE])

    async def revoke_token(self, token) -> None:
        # Stateless by design: to revoke, reset the token in Moodle itself.
        return None
