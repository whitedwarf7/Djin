"""Google Calendar tools: read agenda, find free slots, create events with approval."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from googleapiclient.errors import HttpError

from djin.integrations.google_auth import calendar_service
from djin.tools.registry import Risk, ToolError, register


def _api_error(exc: HttpError) -> ToolError:
    return ToolError(f"Calendar API error: {exc}")


def _parse(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolError(f"{field} must be ISO-8601, e.g. 2026-09-18T14:00:00. Got: {value}") from exc
    return parsed if parsed.tzinfo else parsed.astimezone()


def _format_event(event: dict[str, Any]) -> str:
    start = event.get("start", {})
    end = event.get("end", {})
    when = start.get("dateTime") or start.get("date", "?")
    until = end.get("dateTime") or end.get("date", "?")
    attendees = [a.get("email", "") for a in event.get("attendees", [])]
    line = f"- {when} -> {until} | {event.get('summary', '(no title)')} | id={event.get('id')}"
    if location := event.get("location"):
        line += f" | at {location}"
    if attendees:
        line += f" | attendees: {', '.join(attendees)}"
    return line


@register(
    name="calendar_list_events",
    description=(
        "List Google Calendar events in a time window."
        " Defaults to the next 7 days when no window is given."
    ),
    parameters={
        "type": "object",
        "properties": {
            "time_min": {"type": "string", "description": "ISO-8601 start of window."},
            "time_max": {"type": "string", "description": "ISO-8601 end of window."},
            "max_results": {"type": "integer", "default": 20},
            "calendar_id": {"type": "string", "default": "primary"},
        },
    },
    risk=Risk.READ,
    tags=("calendar",),
)
def calendar_list_events(
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 20,
    calendar_id: str = "primary",
) -> str:
    start = _parse(time_min, "time_min") if time_min else datetime.now(timezone.utc)
    end = _parse(time_max, "time_max") if time_max else start + timedelta(days=7)
    if end <= start:
        raise ToolError("time_max must be after time_min.")

    service = calendar_service()
    try:
        response = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                maxResults=max(1, min(int(max_results), 50)),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
    except HttpError as exc:
        raise _api_error(exc) from exc

    events = response.get("items", [])
    if not events:
        return f"No events between {start.isoformat()} and {end.isoformat()}."
    header = f"Events from {start.isoformat()} to {end.isoformat()}:"
    return header + "\n" + "\n".join(_format_event(event) for event in events)


@register(
    name="calendar_find_free_slots",
    description=(
        "Find free time slots of a given duration within a window,"
        " restricted to the given daily working hours."
    ),
    parameters={
        "type": "object",
        "properties": {
            "time_min": {"type": "string", "description": "ISO-8601 start of window."},
            "time_max": {"type": "string", "description": "ISO-8601 end of window."},
            "duration_minutes": {"type": "integer", "default": 30},
            "work_start_hour": {"type": "integer", "default": 9},
            "work_end_hour": {"type": "integer", "default": 18},
        },
        "required": ["time_min", "time_max"],
    },
    risk=Risk.READ,
    tags=("calendar",),
)
def calendar_find_free_slots(
    time_min: str,
    time_max: str,
    duration_minutes: int = 30,
    work_start_hour: int = 9,
    work_end_hour: int = 18,
) -> str:
    start = _parse(time_min, "time_min")
    end = _parse(time_max, "time_max")
    if end <= start:
        raise ToolError("time_max must be after time_min.")
    if not 0 <= work_start_hour < work_end_hour <= 24:
        raise ToolError("Working hours must satisfy 0 <= work_start_hour < work_end_hour <= 24.")

    service = calendar_service()
    try:
        response = (
            service.freebusy()
            .query(
                body={
                    "timeMin": start.isoformat(),
                    "timeMax": end.isoformat(),
                    "items": [{"id": "primary"}],
                }
            )
            .execute()
        )
    except HttpError as exc:
        raise _api_error(exc) from exc

    busy = [
        (_parse(b["start"], "busy.start"), _parse(b["end"], "busy.end"))
        for b in response.get("calendars", {}).get("primary", {}).get("busy", [])
    ]

    duration = timedelta(minutes=max(5, int(duration_minutes)))
    slots: list[str] = []
    cursor = start
    while cursor + duration <= end and len(slots) < 20:
        local = cursor.astimezone()
        if local.hour < work_start_hour:
            cursor = local.replace(hour=work_start_hour, minute=0, second=0, microsecond=0)
            continue
        if local.hour >= work_end_hour:
            next_day = (local + timedelta(days=1)).replace(
                hour=work_start_hour, minute=0, second=0, microsecond=0
            )
            cursor = next_day
            continue
        slot_end = cursor + duration
        overlap = next((b for b in busy if b[0] < slot_end and cursor < b[1]), None)
        if overlap:
            cursor = overlap[1]
            continue
        slots.append(f"- {cursor.astimezone().isoformat()} -> {slot_end.astimezone().isoformat()}")
        cursor = slot_end

    if not slots:
        return "No free slots found in that window."
    return f"Free {duration_minutes}-minute slots:\n" + "\n".join(slots)


def _event_preview(
    summary: str,
    start: str,
    end: str,
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
    calendar_id: str = "primary",
) -> str:
    lines = [
        "Create calendar event",
        f"Title: {summary}",
        f"Start: {start}",
        f"End: {end}",
        f"Calendar: {calendar_id}",
    ]
    if location:
        lines.append(f"Location: {location}")
    if attendees:
        lines.append(f"Invites will be emailed to: {', '.join(attendees)}")
    if description:
        lines.append(f"\n{description[:500]}")
    return "\n".join(lines)


@register(
    name="calendar_create_event",
    description=(
        "Create a Google Calendar event. Attendees receive an email invitation,"
        " so this action is externally visible and always needs user approval."
    ),
    parameters={
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Event title."},
            "start": {"type": "string", "description": "ISO-8601 start datetime."},
            "end": {"type": "string", "description": "ISO-8601 end datetime."},
            "description": {"type": "string"},
            "location": {"type": "string"},
            "attendees": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Email addresses to invite.",
            },
            "calendar_id": {"type": "string", "default": "primary"},
        },
        "required": ["summary", "start", "end"],
    },
    risk=Risk.EXTERNAL,
    preview=_event_preview,
    tags=("calendar",),
)
def calendar_create_event(
    summary: str,
    start: str,
    end: str,
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
    calendar_id: str = "primary",
) -> str:
    start_dt = _parse(start, "start")
    end_dt = _parse(end, "end")
    if end_dt <= start_dt:
        raise ToolError("Event end must be after start.")

    body: dict[str, Any] = {
        "summary": summary,
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": email} for email in attendees]

    service = calendar_service()
    try:
        event = (
            service.events()
            .insert(
                calendarId=calendar_id,
                body=body,
                sendUpdates="all" if attendees else "none",
            )
            .execute()
        )
    except HttpError as exc:
        raise _api_error(exc) from exc

    return f"Created event '{summary}' (id={event.get('id')}) -> {event.get('htmlLink', '')}"
