"""Approved one-off push notifications."""

from __future__ import annotations

from djin import notifications
from djin.tools.registry import Risk, ToolError, register


def _preview(title: str, message: str) -> str:
    excerpt = message if len(message) <= 600 else message[:600] + "..."
    return f"Send push notification\nTitle: {title}\n\n{excerpt}"


@register(
    name="notification_send",
    description=(
        "Send a push notification through the user's configured ntfy topic."
        " This leaves the computer and always requires approval."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "message": {"type": "string"},
        },
        "required": ["title", "message"],
    },
    risk=Risk.EXTERNAL,
    preview=_preview,
    tags=("notifications",),
)
def notification_send(title: str, message: str) -> str:
    try:
        notifications.send(title, message)
    except notifications.NotificationError as exc:
        raise ToolError(str(exc)) from exc
    return "Push notification sent."