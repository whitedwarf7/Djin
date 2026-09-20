"""Opt-in delivery adapters for proactive Djin results."""

from __future__ import annotations

import httpx

from djin.config import Settings, get_settings

MAX_MESSAGE_CHARS = 3500
MAX_TITLE_CHARS = 100


class NotificationError(RuntimeError):
    pass


def is_configured(settings: Settings | None = None) -> bool:
    return (settings or get_settings()).ntfy_configured


def send(title: str, message: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if not settings.ntfy_configured:
        raise NotificationError("ntfy is not configured.")

    headers = {"Authorization": f"Bearer {settings.ntfy_token}"} if settings.ntfy_token else {}
    payload = {
        "topic": settings.ntfy_topic.strip(),
        "title": title.strip()[:MAX_TITLE_CHARS] or "Djin",
        "message": message.strip()[:MAX_MESSAGE_CHARS] or "Scheduled run completed.",
    }
    try:
        response = httpx.post(
            settings.ntfy_base_url.rstrip("/"),
            json=payload,
            headers=headers,
            timeout=settings.notification_timeout,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise NotificationError(f"ntfy delivery failed: {exc}") from exc