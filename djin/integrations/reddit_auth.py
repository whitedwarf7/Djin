"""Reddit OAuth (authorization code flow, permanent duration)."""

from __future__ import annotations

import secrets as pysecrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import httpx

from djin.config import REDDIT_REDIRECT_PORT, REDDIT_REDIRECT_URI, get_settings
from djin.storage import secrets

SERVICE = "reddit"
SCOPES = ["identity", "read", "mysubreddits", "history"]
AUTHORIZE_URL = "https://www.reddit.com/api/v1/authorize"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"


class NotAuthenticated(RuntimeError):
    pass


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/reddit/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.result = {k: v[0] for k, v in params.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<h3>Djin: Reddit authorisation received. You can close this tab.</h3>")

    def log_message(self, *args: Any) -> None:  # silence request logging
        return


def _basic_auth() -> tuple[str, str]:
    settings = get_settings()
    if not settings.reddit_configured:
        raise NotAuthenticated(
            "Reddit is not configured. Set DJIN_REDDIT_CLIENT_ID and"
            " DJIN_REDDIT_CLIENT_SECRET in .env."
        )
    return settings.reddit_client_id, settings.reddit_client_secret


def run_login(timeout: float = 180.0) -> str:
    client_id, client_secret = _basic_auth()
    state = pysecrets.token_urlsafe(24)
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "state": state,
            "redirect_uri": REDDIT_REDIRECT_URI,
            "duration": "permanent",
            "scope": " ".join(SCOPES),
        }
    )

    _CallbackHandler.result = {}
    server = HTTPServer(("localhost", REDDIT_REDIRECT_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"{AUTHORIZE_URL}?{query}"
        print(f"Opening browser for Reddit authorisation:\n{url}")
        webbrowser.open(url)
        deadline = time.monotonic() + timeout
        while not _CallbackHandler.result and time.monotonic() < deadline:
            time.sleep(0.3)
    finally:
        server.shutdown()
        server.server_close()

    result = _CallbackHandler.result
    if not result:
        raise NotAuthenticated("Timed out waiting for Reddit authorisation.")
    if "error" in result:
        raise NotAuthenticated(f"Reddit returned an error: {result['error']}")
    if not pysecrets.compare_digest(result.get("state", ""), state):
        raise NotAuthenticated("Reddit state mismatch; aborting for safety.")

    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": REDDIT_REDIRECT_URI,
        },
        auth=(client_id, client_secret),
        headers={"User-Agent": get_settings().reddit_user_agent},
        timeout=30,
    )
    if response.status_code >= 400:
        raise NotAuthenticated(f"Reddit token exchange failed: {response.text[:300]}")

    payload = response.json()
    payload["expires_at"] = time.time() + float(payload.get("expires_in", 3600))
    secrets.save_token(SERVICE, payload)
    return username()


def _refresh(payload: dict[str, Any]) -> dict[str, Any]:
    client_id, client_secret = _basic_auth()
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise NotAuthenticated("No Reddit refresh token. Run: python -m djin.cli login reddit")

    response = httpx.post(
        TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        auth=(client_id, client_secret),
        headers={"User-Agent": get_settings().reddit_user_agent},
        timeout=30,
    )
    if response.status_code >= 400:
        raise NotAuthenticated(f"Reddit token refresh failed: {response.text[:300]}")

    refreshed = response.json()
    refreshed.setdefault("refresh_token", refresh_token)
    refreshed["expires_at"] = time.time() + float(refreshed.get("expires_in", 3600))
    secrets.save_token(SERVICE, refreshed)
    return refreshed


def _access_token() -> str:
    payload = secrets.load_token(SERVICE)
    if not payload:
        raise NotAuthenticated("Reddit account not connected. Run: python -m djin.cli login reddit")
    if payload.get("expires_at", 0) - 60 < time.time():
        payload = _refresh(payload)
    return payload["access_token"]


def api_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = httpx.get(
        f"{API_BASE}{path}",
        params=params or {},
        headers={
            "Authorization": f"Bearer {_access_token()}",
            "User-Agent": get_settings().reddit_user_agent,
        },
        timeout=30,
    )
    if response.status_code >= 400:
        raise NotAuthenticated(f"Reddit API error ({response.status_code}): {response.text[:300]}")
    return response.json()


def username() -> str:
    return api_get("/api/v1/me").get("name", "unknown")


def is_connected() -> bool:
    return secrets.has_token(SERVICE)
