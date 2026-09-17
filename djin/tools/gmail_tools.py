"""Gmail tools: read-only search/read plus approval-gated draft creation."""

from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from typing import Any

from googleapiclient.errors import HttpError

from djin.integrations.google_auth import gmail_service
from djin.tools.registry import Risk, ToolError, register, wrap_untrusted

MAX_BODY_CHARS = 8000
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def _decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode()).decode("utf-8", errors="replace")


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    return {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", [])}


def _strip_html(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()


def _extract_body(payload: dict[str, Any]) -> str:
    mime = payload.get("mimeType", "")
    data = (payload.get("body") or {}).get("data")
    if data and mime == "text/plain":
        return _decode(data)
    if data and mime == "text/html":
        return _strip_html(_decode(data))

    html_fallback = ""
    for part in payload.get("parts") or []:
        text = _extract_body(part)
        if not text:
            continue
        if part.get("mimeType") == "text/html":
            html_fallback = html_fallback or text
        else:
            return text
    return html_fallback


def _summarise(message: dict[str, Any]) -> dict[str, Any]:
    headers = _headers(message.get("payload") or {})
    return {
        "id": message.get("id"),
        "thread_id": message.get("threadId"),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", "(no subject)"),
        "date": headers.get("date", ""),
        "snippet": message.get("snippet", ""),
        "labels": message.get("labelIds", []),
    }


def _api_error(exc: HttpError) -> ToolError:
    return ToolError(f"Gmail API error: {exc}")


@register(
    name="gmail_search",
    description=(
        "Search the user's Gmail mailbox and return message summaries."
        " Accepts standard Gmail query syntax such as"
        " 'from:alice@example.com is:unread newer_than:7d'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Gmail search query."},
            "max_results": {
                "type": "integer",
                "description": "How many messages to return (1-25).",
                "default": 10,
            },
        },
        "required": ["query"],
    },
    risk=Risk.READ,
    untrusted_output=True,
    tags=("gmail",),
)
def gmail_search(query: str, max_results: int = 10) -> str:
    service = gmail_service()
    limit = max(1, min(int(max_results), 25))
    try:
        listing = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=limit)
            .execute()
        )
        summaries = []
        for item in listing.get("messages", []):
            message = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=item["id"],
                    format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"],
                )
                .execute()
            )
            summaries.append(_summarise(message))
    except HttpError as exc:
        raise _api_error(exc) from exc

    if not summaries:
        return f"No messages matched the query: {query}"

    lines = [
        f"- id={s['id']} | {s['date']} | from: {s['from']} | subject: {s['subject']}\n"
        f"  snippet: {s['snippet']}"
        for s in summaries
    ]
    return wrap_untrusted("gmail_search", "\n".join(lines))


@register(
    name="gmail_read_message",
    description="Read the full plain-text body and headers of one Gmail message by id.",
    parameters={
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "Gmail message id."},
        },
        "required": ["message_id"],
    },
    risk=Risk.READ,
    untrusted_output=True,
    tags=("gmail",),
)
def gmail_read_message(message_id: str) -> str:
    service = gmail_service()
    try:
        message = (
            service.users().messages().get(userId="me", id=message_id, format="full").execute()
        )
    except HttpError as exc:
        raise _api_error(exc) from exc

    meta = _summarise(message)
    body = _extract_body(message.get("payload") or {}) or message.get("snippet", "")
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + "\n...[truncated]"

    content = (
        f"From: {meta['from']}\nTo: {meta['to']}\nDate: {meta['date']}\n"
        f"Subject: {meta['subject']}\nThread: {meta['thread_id']}\n\n{body}"
    )
    return wrap_untrusted("gmail_message", content)


def _draft_preview(
    to: str, subject: str, body: str, reply_to_message_id: str | None = None
) -> str:
    kind = "Reply draft" if reply_to_message_id else "New draft"
    excerpt = body if len(body) <= 600 else body[:600] + "..."
    return f"{kind}\nTo: {to}\nSubject: {subject}\n\n{excerpt}"


@register(
    name="gmail_create_draft",
    description=(
        "Create a Gmail draft. The draft is saved only, never sent."
        " Provide reply_to_message_id to draft a reply in an existing thread."
    ),
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Comma-separated recipient addresses."},
            "subject": {"type": "string"},
            "body": {"type": "string", "description": "Plain-text body of the email."},
            "reply_to_message_id": {
                "type": "string",
                "description": "Optional Gmail message id being replied to.",
            },
        },
        "required": ["to", "subject", "body"],
    },
    risk=Risk.WRITE,
    preview=_draft_preview,
    tags=("gmail",),
)
def gmail_create_draft(
    to: str, subject: str, body: str, reply_to_message_id: str | None = None
) -> str:
    recipients = [addr.strip() for addr in to.split(",") if addr.strip()]
    if not recipients:
        raise ToolError("No recipient address supplied.")
    for addr in recipients:
        if not EMAIL_RE.match(addr):
            raise ToolError(f"'{addr}' is not a valid email address.")

    service = gmail_service()
    message = EmailMessage()
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)

    draft_body: dict[str, Any] = {}
    if reply_to_message_id:
        try:
            original = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=reply_to_message_id,
                    format="metadata",
                    metadataHeaders=["Message-ID", "References", "Subject"],
                )
                .execute()
            )
        except HttpError as exc:
            raise _api_error(exc) from exc
        headers = _headers(original.get("payload") or {})
        original_id = headers.get("message-id")
        if original_id:
            message["In-Reply-To"] = original_id
            message["References"] = f"{headers.get('references', '')} {original_id}".strip()
        draft_body["threadId"] = original.get("threadId")

    draft_body["raw"] = base64.urlsafe_b64encode(message.as_bytes()).decode()
    try:
        draft = service.users().drafts().create(userId="me", body={"message": draft_body}).execute()
    except HttpError as exc:
        raise _api_error(exc) from exc

    return (
        f"Draft saved (id={draft.get('id')}) to {', '.join(recipients)}"
        f" with subject '{subject}'. It has NOT been sent."
    )
