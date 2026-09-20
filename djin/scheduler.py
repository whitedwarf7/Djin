"""Persistent background schedules for unattended Djin turns."""

from __future__ import annotations

import logging
from datetime import timezone
from threading import RLock
from typing import Any
from zoneinfo import ZoneInfoNotFoundError

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from tzlocal import get_localzone

from djin import notifications
from djin.config import get_settings
from djin.storage import db
from djin.tools.registry import Risk

logger = logging.getLogger(__name__)

_LOCK = RLock()
_SCHEDULER: BackgroundScheduler | None = None
_JOB_PREFIX = "djin-schedule-"


class ScheduleError(ValueError):
    pass


def _timezone(value: str):
    return get_localzone() if value.casefold() == "local" else value


def _trigger(cron: str, timezone_name: str) -> CronTrigger:
    try:
        return CronTrigger.from_crontab(cron, timezone=_timezone(timezone_name))
    except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ScheduleError(f"Invalid schedule: {exc}") from exc


def validate(cron: str, timezone_name: str) -> None:
    if len(cron) > 100:
        raise ScheduleError("Cron expression is too long.")
    _trigger(cron, timezone_name)


def _job_id(schedule_id: str) -> str:
    return f"{_JOB_PREFIX}{schedule_id}"


def _next_run_iso(job: Any) -> str | None:
    next_run = getattr(job, "next_run_time", None)
    return next_run.astimezone(timezone.utc).isoformat() if next_run else None


def _remove_job(schedule_id: str) -> None:
    scheduler = _SCHEDULER
    if scheduler is None:
        return
    try:
        scheduler.remove_job(_job_id(schedule_id))
    except JobLookupError:
        pass


def _install(schedule: dict[str, Any]) -> None:
    scheduler = _SCHEDULER
    if scheduler is None:
        return
    _remove_job(schedule["id"])
    if not schedule["enabled"]:
        db.set_schedule_next_run(schedule["id"], None)
        return
    job = scheduler.add_job(
        _run_schedule,
        _trigger(schedule["cron"], schedule["timezone"]),
        args=[schedule["id"]],
        id=_job_id(schedule["id"]),
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
        replace_existing=True,
    )
    db.set_schedule_next_run(schedule["id"], _next_run_iso(job))


def start() -> bool:
    global _SCHEDULER
    settings = get_settings()
    if not settings.scheduler_enabled:
        return False
    with _LOCK:
        if _SCHEDULER is not None:
            return True
        scheduler = BackgroundScheduler(timezone=_timezone(settings.scheduler_timezone))
        scheduler.start()
        _SCHEDULER = scheduler
        for schedule in db.list_schedules(enabled_only=True):
            try:
                _install(schedule)
            except ScheduleError as exc:
                db.record_schedule_run(
                    schedule["id"], status="error", conversation_id=None, error=str(exc)
                )
                logger.warning("Could not load schedule %s: %s", schedule["id"], exc)
    return True


def shutdown() -> None:
    global _SCHEDULER
    with _LOCK:
        scheduler, _SCHEDULER = _SCHEDULER, None
    if scheduler is not None:
        scheduler.shutdown(wait=False)


def is_running() -> bool:
    return _SCHEDULER is not None


def create(
    *,
    name: str,
    prompt: str,
    cron: str,
    timezone_name: str | None = None,
    risk_ceiling: str = "read",
    notify: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    timezone_name = timezone_name or settings.scheduler_timezone
    name = " ".join(name.split())
    prompt = prompt.strip()
    if not name or len(name) > 100:
        raise ScheduleError("Schedule name must be between 1 and 100 characters.")
    if not prompt or len(prompt) > 20_000:
        raise ScheduleError("Schedule prompt must be between 1 and 20,000 characters.")
    if risk_ceiling not in {Risk.READ.value, Risk.WRITE.value}:
        raise ScheduleError("Risk ceiling must be read or write.")
    validate(cron, timezone_name)
    schedule = db.create_schedule(
        name=name,
        prompt=prompt,
        cron=cron,
        timezone_name=timezone_name,
        risk_ceiling=risk_ceiling,
        notify=notify,
    )
    with _LOCK:
        _install(schedule)
    return db.get_schedule(schedule["id"]) or schedule


def set_enabled(schedule_id: str, enabled: bool) -> dict[str, Any]:
    schedule = db.set_schedule_enabled(schedule_id, enabled)
    if schedule is None:
        raise ScheduleError(f"No such schedule: {schedule_id}")
    with _LOCK:
        _install(schedule)
    return db.get_schedule(schedule_id) or schedule


def delete(schedule_id: str) -> None:
    if db.get_schedule(schedule_id) is None:
        raise ScheduleError(f"No such schedule: {schedule_id}")
    with _LOCK:
        _remove_job(schedule_id)
    db.delete_schedule(schedule_id)


def _run_schedule(schedule_id: str) -> None:
    schedule = db.get_schedule(schedule_id)
    if schedule is None or not schedule["enabled"]:
        return

    conversation_id: str | None = None
    try:
        from djin import agent

        result = agent.start_turn(
            None,
            schedule["prompt"],
            risk_ceiling=Risk(schedule["risk_ceiling"]),
        )
        conversation_id = result.conversation_id or None
        if conversation_id:
            db.set_conversation_title(conversation_id, f"Scheduled: {schedule['name']}")
        if result.error:
            status = "error"
            error = result.error
            message = f"Scheduled run failed: {result.error}"
        elif result.pending:
            status = "pending"
            error = "The scheduled turn requires approval."
            message = error
        else:
            status = "ok"
            error = None
            message = result.reply or "Scheduled run completed."

        if schedule["notify"] and notifications.is_configured():
            try:
                notifications.send(schedule["name"], message)
            except notifications.NotificationError as exc:
                delivery_error = str(exc)
                error = f"{error} {delivery_error}".strip() if error else delivery_error
                if status == "ok":
                    status = "delivery_error"

        db.record_schedule_run(
            schedule_id,
            status=status,
            conversation_id=conversation_id,
            error=error,
        )
    except Exception as exc:
        logger.exception("Scheduled run %s failed", schedule_id)
        db.record_schedule_run(
            schedule_id,
            status="error",
            conversation_id=conversation_id,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        scheduler = _SCHEDULER
        job = scheduler.get_job(_job_id(schedule_id)) if scheduler else None
        db.set_schedule_next_run(schedule_id, _next_run_iso(job) if job else None)