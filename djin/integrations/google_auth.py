"""Google OAuth (desktop flow) with encrypted token storage."""

from __future__ import annotations

import json
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from djin.config import get_settings
from djin.storage import secrets

SERVICE = "google"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


class NotAuthenticated(RuntimeError):
    pass


def _client_config() -> dict[str, Any]:
    settings = get_settings()
    if not settings.google_configured:
        raise NotAuthenticated(
            "Google is not configured. Set DJIN_GOOGLE_CLIENT_ID and"
            " DJIN_GOOGLE_CLIENT_SECRET in .env."
        )
    return {
        "installed": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def run_login() -> str:
    """Open a browser for consent and store the resulting refresh token."""
    flow = InstalledAppFlow.from_client_config(_client_config(), SCOPES)
    credentials = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    secrets.save_token(SERVICE, json.loads(credentials.to_json()))
    return _account_email(credentials)


def get_credentials() -> Credentials:
    payload = secrets.load_token(SERVICE)
    if not payload:
        raise NotAuthenticated("Google account not connected. Run: python -m djin.cli login google")

    credentials = Credentials.from_authorized_user_info(payload, SCOPES)
    if missing := set(SCOPES) - set(credentials.scopes or []):
        raise NotAuthenticated(
            "Stored Google token is missing scopes: "
            + ", ".join(sorted(missing))
            + ". Re-run: python -m djin.cli login google"
        )

    if not credentials.valid:
        if not credentials.refresh_token:
            raise NotAuthenticated("Google token expired. Re-run: python -m djin.cli login google")
        try:
            credentials.refresh(Request())
        except RefreshError as exc:
            raise NotAuthenticated(
                "Google token refresh failed. Re-run: python -m djin.cli login google"
            ) from exc
        secrets.save_token(SERVICE, json.loads(credentials.to_json()))
    return credentials


def gmail_service():
    return build("gmail", "v1", credentials=get_credentials(), cache_discovery=False)


def calendar_service():
    return build("calendar", "v3", credentials=get_credentials(), cache_discovery=False)


def _account_email(credentials: Credentials) -> str:
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    return service.users().getProfile(userId="me").execute().get("emailAddress", "unknown")


def account_email() -> str:
    return _account_email(get_credentials())


def is_connected() -> bool:
    return secrets.has_token(SERVICE)
