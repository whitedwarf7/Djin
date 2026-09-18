"""Gmail tools: filtered search, inbox digest, thread reading, approval-gated drafts.

Message fetches go out as batched requests (one HTTP round trip instead of one per
message), are cached briefly, and bodies are stripped of quoted replies, signatures and
boilerplate before they reach the model.
"""

from __future__ import annotations

import base64
import html
import re
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any

from googleapiclient.errors import HttpError

from djin.integrations.google_auth import gmail_service
from djin.tools.registry import Risk, ToolError, register, wrap_untrusted

MAX_BODY_CHARS = 6000
MAX_THREAD_CHARS = 14000
BATCH_SIZE = 50
CACHE_TTL_SECONDS = 180.0
CACHE_MAX_ENTRIES = 200

EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")

METADATA_HEADERS = ["From", "To", "Cc", "Subject", "Date", "List-Unsubscribe"]
METADATA_FIELDS = "id,threadId,snippet,labelIds,internalDate,payload/headers"
FULL_FIELDS = "id,threadId,snippet,labelIds,internalDate,payload"
THREAD_FIELDS = "id,messages(id,threadId,snippet,labelIds,internalDate,payload)"

CATEGORIES = ("primary", "social", "promotions", "updates", "forums")
NOISE_CATEGORIES = ("promotions", "social", "forums")
BULK_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS"}


# --------------------------------------------------------------------------- cache

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _cache_get(key: str) -> dict[str, Any] | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    stored_at, value = entry
    if time.monotonic() - stored_at > CACHE_TTL_SECONDS:
        _CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: dict[str, Any]) -> None:
    if len(_CACHE) >= CACHE_MAX_ENTRIES:
        _CACHE.pop(min(_CACHE, key=lambda item: _CACHE[item][0]), None)
    _CACHE[key] = (time.monotonic(), value)


# --------------------------------------------------------------------------- fetching


def _api_error(exc: HttpError) -> ToolError:
    return ToolError(f"Gmail API error: {exc}")


def _get_request(service: Any, message_id: str, fmt: str) -> Any:
    kwargs: dict[str, Any] = {"userId": "me", "id": message_id, "format": fmt}
    if fmt == "metadata":
        kwargs["metadataHeaders"] = METADATA_HEADERS
        kwargs["fields"] = METADATA_FIELDS
    else:
        kwargs["fields"] = FULL_FIELDS
    return service.users().messages().get(**kwargs)


def _batch_get(service: Any, ids: list[str], fmt: str) -> list[dict[str, Any]] | None:
    """One HTTP request per BATCH_SIZE messages. Returns None if batching is unusable."""
    collected: dict[str, dict[str, Any]] = {}

    def _collect(request_id: str, response: dict[str, Any] | None, exception: Any) -> None:
        if exception is None and response:
            collected[request_id] = response

    try:
        for start in range(0, len(ids), BATCH_SIZE):
            batch = service.new_batch_http_request(callback=_collect)
            for message_id in ids[start : start + BATCH_SIZE]:
                batch.add(_get_request(service, message_id, fmt), request_id=message_id)
            batch.execute()
    except Exception:  # fall back to one-by-one rather than losing the whole turn
        return None
    return None if not collected else [collected[mid] for mid in ids if mid in collected]


def _sequential_get(service: Any, ids: list[str], fmt: str) -> list[dict[str, Any]]:
    messages = []
    for message_id in ids:
        try:
            messages.append(_get_request(service, message_id, fmt).execute())
        except HttpError:
            continue
    return messages


def _fetch_messages(service: Any, ids: list[str], fmt: str = "metadata") -> list[dict[str, Any]]:
    missing = [mid for mid in ids if _cache_get(f"{fmt}:{mid}") is None]
    if missing:
        fetched = _batch_get(service, missing, fmt)
        if fetched is None:
            fetched = _sequential_get(service, missing, fmt)
        for message in fetched:
            if message.get("id"):
                _cache_put(f"{fmt}:{message['id']}", message)

    result = []
    for message_id in ids:
        cached = _cache_get(f"{fmt}:{message_id}")
        if cached is not None:
            result.append(cached)
    return result


def _list_ids(service: Any, query: str, limit: int) -> list[str]:
    try:
        listing = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=limit, fields="messages/id")
            .execute()
        )
    except HttpError as exc:
        raise _api_error(exc) from exc
    return [item["id"] for item in listing.get("messages", []) if item.get("id")]


# --------------------------------------------------------------------------- query building


def _term(value: str) -> str:
    value = value.strip()
    return f'"{value}"' if " " in value else value


def _clamp_days(value: int | None, field: str) -> int | None:
    if value is None:
        return None
    days = int(value)
    if days < 1:
        raise ToolError(f"{field} must be at least 1.")
    return min(days, 3650)


def _build_query(
    query: str | None = None,
    sender: str | None = None,
    recipient: str | None = None,
    subject: str | None = None,
    label: str | None = None,
    category: str | None = None,
    is_unread: bool | None = None,
    is_important: bool | None = None,
    has_attachment: bool | None = None,
    newer_than_days: int | None = None,
    older_than_days: int | None = None,
    exclude_senders: list[str] | None = None,
    exclude_noise: bool = False,
) -> str:
    terms: list[str] = []

    if query and query.strip():
        terms.append(query.strip())
    if sender:
        terms.append(f"from:{_term(sender)}")
    if recipient:
        terms.append(f"to:{_term(recipient)}")
    if subject:
        terms.append(f"subject:{_term(subject)}")
    if label:
        terms.append(f"label:{_term(label)}")

    if category:
        normalised = category.strip().lower()
        if normalised not in CATEGORIES:
            raise ToolError(f"category must be one of: {', '.join(CATEGORIES)}")
        terms.append(f"category:{normalised}")

    if is_unread is not None:
        terms.append("is:unread" if is_unread else "is:read")
    if is_important:
        terms.append("is:important")
    if has_attachment:
        terms.append("has:attachment")

    if days := _clamp_days(newer_than_days, "newer_than_days"):
        terms.append(f"newer_than:{days}d")
    if days := _clamp_days(older_than_days, "older_than_days"):
        terms.append(f"older_than:{days}d")

    for address in exclude_senders or []:
        if address.strip():
            terms.append(f"-from:{_term(address)}")

    if exclude_noise:
        terms.extend(f"-category:{name}" for name in NOISE_CATEGORIES if name != category)

    return " ".join(terms) if terms else "in:inbox"


# --------------------------------------------------------------------------- body cleaning

NBSP = "\u00a0"

QUOTE_HEADER = re.compile(
    r"^\s*(?:"
    r"on\s.{6,200}\s(?:wrote|schrieb):"
    r"|-{2,}\s*(?:original message|forwarded message|urspr\u00fcngliche nachricht)\s*-{2,}"
    r"|_{10,}"
    r"|begin forwarded message:"
    r")\s*$",
    re.IGNORECASE,
)
OUTLOOK_FROM = re.compile(r"^\**\s*(?:from|von):\s*\S", re.IGNORECASE)
OUTLOOK_FIELDS = re.compile(
    r"(?:^|\s)(?:sent|date|gesendet|to|an|subject|betreff):\s", re.IGNORECASE
)
SIGNATURE = re.compile(r"^--\s?$")
BOILERPLATE = re.compile(
    r"^\s*(?:"
    r"this (?:e-?mail|message).{0,80}(?:confidential|intended (?:only |solely )?for)"
    r"|confidentiality notice"
    r"|if you (?:have )?received this (?:e-?mail|message) in error"
    r"|you (?:are )?receiv(?:ed?|ing) this (?:e-?mail|message) because"
    r"|(?:click here to )?unsubscribe"
    r"|view (?:this (?:e-?mail|message)|it) in your browser"
    r"|manage your (?:e-?mail )?preferences"
    r"|sent from my \w+"
    r")",
    re.IGNORECASE,
)
LONG_URL = re.compile(r"https?://\S{100,}")


def _decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode()).decode("utf-8", errors="replace")


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    return {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", [])}


def _strip_html(markup: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(markup, "html.parser")
    for tag in soup(["script", "style", "head", "title"]):
        tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()


def _walk_parts(part: dict[str, Any]) -> tuple[str, str]:
    """Returns (plain text, html) found in this part, ignoring attachments."""
    if part.get("filename"):
        return "", ""

    mime = part.get("mimeType", "")
    data = (part.get("body") or {}).get("data")
    if data:
        if mime == "text/plain":
            return _decode(data), ""
        if mime == "text/html":
            return "", _decode(data)
        return "", ""

    plain: list[str] = []
    markup: list[str] = []
    for child in part.get("parts") or []:
        child_plain, child_html = _walk_parts(child)
        if child_plain:
            plain.append(child_plain)
        if child_html:
            markup.append(child_html)
    return "\n".join(plain), "\n".join(markup)


def _extract_body(payload: dict[str, Any]) -> str:
    plain, markup = _walk_parts(payload)
    if plain.strip():
        return plain
    return _strip_html(markup) if markup else ""


def _is_quote_start(lines: list[str], index: int) -> bool:
    if QUOTE_HEADER.match(lines[index]):
        return True
    if OUTLOOK_FROM.match(lines[index]):
        return bool(OUTLOOK_FIELDS.search(" ".join(lines[index + 1 : index + 5])))
    return False


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "\n...[truncated]"


def _clean_body(text: str, limit: int = MAX_BODY_CHARS, keep_quotes: bool = False) -> str:
    """Drop quoted replies, signatures and legal/marketing boilerplate."""
    normalised = text.replace("\r\n", "\n").replace("\r", "\n").replace(NBSP, " ")
    if keep_quotes:
        return _truncate(re.sub(r"\n{3,}", "\n\n", normalised).strip(), limit)

    lines = normalised.split("\n")
    kept: list[str] = []
    length = 0
    for index, raw in enumerate(lines):
        line = raw.rstrip()
        if _is_quote_start(lines, index) or SIGNATURE.match(line):
            break
        if BOILERPLATE.match(line):
            # Near the top this is a banner worth skipping; further down it is the footer.
            if length > 200:
                break
            continue
        if line.lstrip().startswith(">"):
            continue
        cleaned = LONG_URL.sub(lambda match: match.group(0)[:60] + "\u2026[link trimmed]", line)
        kept.append(re.sub(r"[ \t]{2,}", " ", cleaned))
        length += len(cleaned)

    body = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    if not body:  # the message was nothing but quotes; showing them beats showing nothing
        body = re.sub(r"\n{3,}", "\n\n", normalised).strip()
    return _truncate(body, limit)


# --------------------------------------------------------------------------- formatting


def _summarise(message: dict[str, Any]) -> dict[str, Any]:
    headers = _headers(message.get("payload") or {})
    labels = message.get("labelIds") or []
    return {
        "id": message.get("id", ""),
        "thread_id": message.get("threadId", ""),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "cc": headers.get("cc", ""),
        "subject": headers.get("subject") or "(no subject)",
        "date": headers.get("date", ""),
        "timestamp": int(message.get("internalDate") or 0),
        "snippet": html.unescape(message.get("snippet") or ""),
        "labels": labels,
        "unread": "UNREAD" in labels,
        "important": "IMPORTANT" in labels or "STARRED" in labels,
        "bulk": bool(headers.get("list-unsubscribe")) or bool(BULK_LABELS & set(labels)),
    }


def _short(text: str, limit: int) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "\u2026"


def _sender_name(value: str) -> str:
    name, address = parseaddr(value)
    return _short(name.strip() or address or value, 48)


def _sender_key(value: str) -> str:
    _, address = parseaddr(value)
    return (address or value).lower()


def _when(message: dict[str, Any]) -> str:
    if message["timestamp"]:
        return datetime.fromtimestamp(message["timestamp"] / 1000).strftime("%Y-%m-%d %H:%M")
    return message["date"] or "unknown date"


def _flags(message: dict[str, Any]) -> str:
    marks = [
        name
        for name, present in (
            ("unread", message["unread"]),
            ("important", message["important"]),
            ("bulk", message["bulk"]),
        )
        if present
    ]
    return f" [{'/'.join(marks)}]" if marks else ""


def _message_line(message: dict[str, Any], with_snippet: bool = True) -> str:
    line = (
        f"- {message['id']} | {_when(message)} | {_sender_name(message['from'])}"
        f" | {_short(message['subject'], 90)}{_flags(message)}"
    )
    if with_snippet and message["snippet"]:
        line += f"\n    {_short(message['snippet'], 160)}"
    return line


def _group_threads(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for message in messages:
        grouped.setdefault(message["thread_id"] or message["id"], []).append(message)

    threads = []
    for thread_id, items in grouped.items():
        items.sort(key=lambda item: item["timestamp"])
        threads.append(
            {
                "thread_id": thread_id,
                "count": len(items),
                "unread": sum(1 for item in items if item["unread"]),
                "important": any(item["important"] for item in items),
                "bulk": all(item["bulk"] for item in items),
                "latest": items[-1],
            }
        )
    threads.sort(key=lambda thread: thread["latest"]["timestamp"], reverse=True)
    return threads


def _thread_line(thread: dict[str, Any]) -> str:
    latest = thread["latest"]
    parts = [f"- thread={thread['thread_id']}", _when(latest), _sender_name(latest["from"])]
    if thread["count"] > 1:
        parts.append(f"{thread['count']} msgs")
    if thread["unread"]:
        parts.append(f"{thread['unread']} unread")
    return (
        f"{' | '.join(parts)} | {_short(latest['subject'], 90)}"
        f"\n    {_short(latest['snippet'], 160)}"
    )


# --------------------------------------------------------------------------- tools

SEARCH_FILTERS: dict[str, Any] = {
    "query": {
        "type": "string",
        "description": "Extra raw Gmail query terms for anything the filters cannot express.",
    },
    "sender": {"type": "string", "description": "Match the From address or name."},
    "recipient": {"type": "string", "description": "Match the To address."},
    "subject": {"type": "string", "description": "Words that must appear in the subject."},
    "label": {"type": "string", "description": "Gmail label name, e.g. 'inbox' or 'Work'."},
    "category": {
        "type": "string",
        "enum": list(CATEGORIES),
        "description": "Gmail inbox category.",
    },
    "is_unread": {"type": "boolean", "description": "True for unread only, false for read only."},
    "is_important": {"type": "boolean", "description": "Only important or starred messages."},
    "has_attachment": {"type": "boolean", "description": "Only messages with attachments."},
    "newer_than_days": {"type": "integer", "description": "Only messages from the last N days."},
    "older_than_days": {"type": "integer", "description": "Only messages older than N days."},
    "exclude_senders": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Addresses or domains to leave out, e.g. ['noreply@github.com'].",
    },
    "exclude_noise": {
        "type": "boolean",
        "description": "Drop the promotions, social and forums categories.",
        "default": False,
    },
}



@register(
    name="gmail_search",
    description=(
        "Search Gmail using structured filters instead of hand-written query syntax."
        " Combine sender, subject, label, category, unread state and age;"
        " use `query` only for terms the filters do not cover."
        " Returns one compact line per message, newest first, with the id needed to read it."
    ),
    parameters={
        "type": "object",
        "properties": {
            **SEARCH_FILTERS,
            "include_snippets": {
                "type": "boolean",
                "description": "Include a one-line preview of each message.",
                "default": True,
            },
            "max_results": {
                "type": "integer",
                "description": "How many messages to return (1-50).",
                "default": 15,
            },
        },
    },
    risk=Risk.READ,
    untrusted_output=True,
    tags=("gmail",),
)
def gmail_search(
    query: str | None = None,
    sender: str | None = None,
    recipient: str | None = None,
    subject: str | None = None,
    label: str | None = None,
    category: str | None = None,
    is_unread: bool | None = None,
    is_important: bool | None = None,
    has_attachment: bool | None = None,
    newer_than_days: int | None = None,
    older_than_days: int | None = None,
    exclude_senders: list[str] | None = None,
    exclude_noise: bool = False,
    include_snippets: bool = True,
    max_results: int = 15,
) -> str:
    search = _build_query(
        query=query,
        sender=sender,
        recipient=recipient,
        subject=subject,
        label=label,
        category=category,
        is_unread=is_unread,
        is_important=is_important,
        has_attachment=has_attachment,
        newer_than_days=newer_than_days,
        older_than_days=older_than_days,
        exclude_senders=exclude_senders,
        exclude_noise=exclude_noise,
    )

    service = gmail_service()
    ids = _list_ids(service, search, max(1, min(int(max_results), 50)))
    if not ids:
        return f"No messages matched: {search}"

    messages = [_summarise(message) for message in _fetch_messages(service, ids, "metadata")]
    messages.sort(key=lambda message: message["timestamp"], reverse=True)
    unread = sum(1 for message in messages if message["unread"])

    header = f"query: {search}\n{len(messages)} message(s), {unread} unread"
    body = "\n".join(_message_line(message, include_snippets) for message in messages)
    return wrap_untrusted("gmail_search", f"{header}\n{body}")


@register(
    name="gmail_digest",
    description=(
        "Summarise the mailbox in one call: messages grouped into conversations and split"
        " into important, direct and bulk/newsletter sections, with counts per sender."
        " Use this instead of gmail_search when the user asks what is in their mail,"
        " what they missed, or for a summary of the day."
    ),
    parameters={
        "type": "object",
        "properties": {
            "newer_than_days": {
                "type": "integer",
                "description": "How far back to look.",
                "default": 1,
            },
            "only_unread": {"type": "boolean", "description": "Unread only.", "default": True},
            "exclude_noise": {
                "type": "boolean",
                "description": "Leave promotions, social and forums out entirely.",
                "default": False,
            },
            "label": {"type": "string", "description": "Restrict to a label.", "default": "inbox"},
            "query": {"type": "string", "description": "Extra raw Gmail query terms."},
            "max_messages": {
                "type": "integer",
                "description": "Upper bound on messages scanned (1-100).",
                "default": 60,
            },
        },
    },
    risk=Risk.READ,
    untrusted_output=True,
    tags=("gmail",),
)
def gmail_digest(
    newer_than_days: int = 1,
    only_unread: bool = True,
    exclude_noise: bool = False,
    label: str = "inbox",
    query: str | None = None,
    max_messages: int = 60,
) -> str:
    search = _build_query(
        query=query,
        label=label or "inbox",
        is_unread=True if only_unread else None,
        newer_than_days=newer_than_days,
        exclude_noise=exclude_noise,
    )

    service = gmail_service()
    ids = _list_ids(service, search, max(1, min(int(max_messages), 100)))
    if not ids:
        return f"Nothing to report. No messages matched: {search}"

    messages = [_summarise(message) for message in _fetch_messages(service, ids, "metadata")]
    threads = _group_threads(messages)
    unread = sum(1 for message in messages if message["unread"])

    important = [thread for thread in threads if thread["important"]]
    bulk = [thread for thread in threads if not thread["important"] and thread["bulk"]]
    direct = [thread for thread in threads if not thread["important"] and not thread["bulk"]]

    sections = [
        f"query: {search}",
        f"{len(messages)} message(s) in {len(threads)} conversation(s), {unread} unread",
    ]
    if important:
        sections.append(f"\nIMPORTANT OR STARRED ({len(important)})")
        sections.extend(_thread_line(thread) for thread in important)
    if direct:
        sections.append(f"\nCONVERSATIONS ({len(direct)})")
        sections.extend(_thread_line(thread) for thread in direct)
    if bulk:
        sections.extend(_bulk_section(bulk))

    return wrap_untrusted("gmail_digest", "\n".join(sections))


def _bulk_section(threads: list[dict[str, Any]]) -> list[str]:
    """Newsletters collapse to one line per sender; individual subjects are rarely useful."""
    senders: dict[str, dict[str, Any]] = {}
    for thread in threads:
        latest = thread["latest"]
        entry = senders.setdefault(
            _sender_key(latest["from"]),
            {"name": _sender_name(latest["from"]), "count": 0, "unread": 0, "subject": ""},
        )
        entry["count"] += thread["count"]
        entry["unread"] += thread["unread"]
        entry["subject"] = entry["subject"] or _short(latest["subject"], 70)

    ranked = sorted(senders.values(), key=lambda item: item["count"], reverse=True)
    total = sum(item["count"] for item in ranked)
    lines = [f"\nBULK AND NEWSLETTERS ({total} messages from {len(ranked)} senders)"]
    lines.extend(
        f"- {item['name']} \u2014 {item['count']} message(s), {item['unread']} unread"
        f" \u00b7 latest: {item['subject']}"
        for item in ranked
    )
    return lines


@register(
    name="gmail_read_message",
    description=(
        "Read one Gmail message by id. Quoted replies, signatures and legal footers are"
        " removed by default; set include_quotes to see the raw body."
    ),
    parameters={
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "Gmail message id."},
            "include_quotes": {
                "type": "boolean",
                "description": "Keep quoted history and footers.",
                "default": False,
            },
        },
        "required": ["message_id"],
    },
    risk=Risk.READ,
    untrusted_output=True,
    tags=("gmail",),
)
def gmail_read_message(message_id: str, include_quotes: bool = False) -> str:
    service = gmail_service()
    messages = _fetch_messages(service, [message_id], "full")
    if not messages:
        raise ToolError(f"Message '{message_id}' could not be read.")

    message = messages[0]
    meta = _summarise(message)
    raw = _extract_body(message.get("payload") or {}) or meta["snippet"]
    body = _clean_body(raw, MAX_BODY_CHARS, keep_quotes=include_quotes)

    content = (
        f"From: {meta['from']}\nTo: {meta['to']}\nDate: {_when(meta)}\n"
        f"Subject: {meta['subject']}\nThread: {meta['thread_id']}{_flags(meta)}\n\n{body}"
    )
    return wrap_untrusted("gmail_message", content)


def _dedupe_lines(body: str, seen: set[str]) -> str:
    """Drop substantial lines already shown by an earlier message in the thread."""
    kept = []
    for line in body.split("\n"):
        key = re.sub(r"\s+", " ", line).strip().lower()
        if len(key) > 40:
            if key in seen:
                continue
            seen.add(key)
        kept.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


@register(
    name="gmail_read_thread",
    description=(
        "Read a whole Gmail conversation in one call, oldest message first, with quoted"
        " history and text repeated between messages removed."
        " Always prefer this over calling gmail_read_message once per message in a thread."
    ),
    parameters={
        "type": "object",
        "properties": {
            "thread_id": {"type": "string", "description": "Gmail thread id."},
            "max_messages": {
                "type": "integer",
                "description": "Read at most the newest N messages (1-30).",
                "default": 15,
            },
        },
        "required": ["thread_id"],
    },
    risk=Risk.READ,
    untrusted_output=True,
    tags=("gmail",),
)
def gmail_read_thread(thread_id: str, max_messages: int = 15) -> str:
    service = gmail_service()
    try:
        thread = (
            service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full", fields=THREAD_FIELDS)
            .execute()
        )
    except HttpError as exc:
        raise _api_error(exc) from exc

    raw_messages = thread.get("messages") or []
    if not raw_messages:
        raise ToolError(f"Thread '{thread_id}' has no readable messages.")

    selected = raw_messages[-max(1, min(int(max_messages), 30)) :]
    per_message = max(600, MAX_THREAD_CHARS // len(selected))
    omitted = len(raw_messages) - len(selected)

    seen: set[str] = set()
    blocks = []
    for message in selected:
        meta = _summarise(message)
        raw = _extract_body(message.get("payload") or {}) or meta["snippet"]
        body = _dedupe_lines(_clean_body(raw, per_message), seen)
        blocks.append(f"--- {_when(meta)} | {meta['from']} | id={meta['id']}{_flags(meta)}\n{body}")

    header = (
        f"Thread {thread_id} \u00b7 {len(raw_messages)} message(s)"
        f"{f', {omitted} older omitted' if omitted else ''}\n"
        f"Subject: {_summarise(selected[-1])['subject']}"
    )
    content = _truncate(f"{header}\n\n" + "\n\n".join(blocks), MAX_THREAD_CHARS)
    return wrap_untrusted("gmail_thread", content)


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
