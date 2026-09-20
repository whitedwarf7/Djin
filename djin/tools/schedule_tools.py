"""Recurring unattended turns, persisted in SQLite and run by APScheduler."""

from __future__ import annotations

from djin import scheduler
from djin.config import get_settings
from djin.storage import db
from djin.tools.registry import Risk, ToolError, register


def _summary(schedule: dict[str, object]) -> str:
    state = "enabled" if schedule["enabled"] else "paused"
    delivery = "push" if schedule["notify"] else "local only"
    next_run = schedule["next_run_at"] or "not scheduled"
    last = schedule["last_status"] or "never run"
    prompt = " ".join(str(schedule["prompt"]).split())
    if len(prompt) > 140:
        prompt = prompt[:137] + "..."
    return (
        f"- {schedule['name']} [{schedule['id']}]\n"
        f"  {schedule['cron']} ({schedule['timezone']}); {state};"
        f" {schedule['risk_ceiling']} ceiling; {delivery}\n"
        f"  Next: {next_run}; last: {last}\n"
        f"  Prompt: {prompt}"
    )


@register(
    name="schedule_list",
    description="List recurring Djin schedules, including their ids, timing and last result.",
    parameters={
        "type": "object",
        "properties": {
            "enabled_only": {
                "type": "boolean",
                "default": False,
                "description": "Return only schedules that are currently enabled.",
            }
        },
    },
    risk=Risk.READ,
    tags=("scheduler",),
)
def schedule_list(enabled_only: bool = False) -> str:
    schedules = db.list_schedules(enabled_only=enabled_only)
    if not schedules:
        return "No recurring schedules found."
    return "Recurring schedules:\n" + "\n".join(_summary(item) for item in schedules)


def _create_preview(
    name: str,
    prompt: str,
    cron: str,
    timezone: str | None = None,
    risk_ceiling: str = "read",
    notify: bool = True,
) -> str:
    excerpt = prompt if len(prompt) <= 600 else prompt[:600] + "..."
    timezone_name = timezone or get_settings().scheduler_timezone
    return (
        "Create recurring schedule\n"
        f"Name: {name}\n"
        f"When: {cron} ({timezone_name})\n"
        f"Maximum tool risk: {risk_ceiling}\n"
        f"Push result: {'yes' if notify else 'no'}\n\n"
        f"{excerpt}"
    )


@register(
    name="schedule_create",
    description=(
        "Create a recurring unattended Djin turn from a five-field cron expression."
        " Use the local timezone unless the user explicitly names an IANA timezone."
        " Default to a read risk ceiling. Creating recurring autonomy always requires approval."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short schedule name."},
            "prompt": {
                "type": "string",
                "description": "The complete instruction Djin should run each time.",
            },
            "cron": {
                "type": "string",
                "description": "Five fields: minute hour day-of-month month day-of-week.",
            },
            "timezone": {
                "type": "string",
                "description": (
                    "Optional override: 'local' or an IANA name such as Europe/Berlin."
                ),
            },
            "risk_ceiling": {
                "type": "string",
                "enum": ["read", "write"],
                "default": "read",
                "description": "Highest tool risk allowed during unattended runs.",
            },
            "notify": {
                "type": "boolean",
                "default": True,
                "description": "Push the final result through ntfy when configured.",
            },
        },
        "required": ["name", "prompt", "cron"],
    },
    risk=Risk.EXTERNAL,
    preview=_create_preview,
    tags=("scheduler",),
)
def schedule_create(
    name: str,
    prompt: str,
    cron: str,
    timezone: str | None = None,
    risk_ceiling: str = "read",
    notify: bool = True,
) -> str:
    try:
        schedule = scheduler.create(
            name=name,
            prompt=prompt,
            cron=cron,
            timezone_name=timezone,
            risk_ceiling=risk_ceiling,
            notify=notify,
        )
    except scheduler.ScheduleError as exc:
        raise ToolError(str(exc)) from exc
    return "Created schedule:\n" + _summary(schedule)


def _enabled_preview(schedule_id: str, enabled: bool) -> str:
    action = "Resume" if enabled else "Pause"
    return f"{action} recurring schedule {schedule_id}."


@register(
    name="schedule_set_enabled",
    description="Pause or resume an existing recurring schedule by id.",
    parameters={
        "type": "object",
        "properties": {
            "schedule_id": {"type": "string"},
            "enabled": {"type": "boolean"},
        },
        "required": ["schedule_id", "enabled"],
    },
    risk=Risk.EXTERNAL,
    preview=_enabled_preview,
    tags=("scheduler",),
)
def schedule_set_enabled(schedule_id: str, enabled: bool) -> str:
    try:
        schedule = scheduler.set_enabled(schedule_id, enabled)
    except scheduler.ScheduleError as exc:
        raise ToolError(str(exc)) from exc
    return ("Resumed" if enabled else "Paused") + f" schedule '{schedule['name']}'."


def _delete_preview(schedule_id: str) -> str:
    schedule = db.get_schedule(schedule_id)
    name = f" '{schedule['name']}'" if schedule else ""
    return f"Permanently delete recurring schedule{name} ({schedule_id})."


@register(
    name="schedule_delete",
    description="Permanently delete a recurring schedule by id.",
    parameters={
        "type": "object",
        "properties": {"schedule_id": {"type": "string"}},
        "required": ["schedule_id"],
    },
    risk=Risk.DESTRUCTIVE,
    preview=_delete_preview,
    tags=("scheduler",),
)
def schedule_delete(schedule_id: str) -> str:
    schedule = db.get_schedule(schedule_id)
    try:
        scheduler.delete(schedule_id)
    except scheduler.ScheduleError as exc:
        raise ToolError(str(exc)) from exc
    name = schedule["name"] if schedule else schedule_id
    return f"Deleted schedule '{name}'."