"""Persistent local research queue and schedule management."""
import asyncio
import json
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import Field, model_validator

from .research_data import cash_hours, close_buffer_minutes, exchange_calendar, exchange_sessions, market_zone
from .research_models import ResearchConfig
from .research_store import connect
from .persistence.jobs import JobRepository, MissingRecord, StateConflict
from .persistence.models import Job, Schedule as StoredSchedule
from sqlalchemy import select
from .jobs.runner import run_job
from .scheduled_briefs import PRICE_WORKFLOWS, BriefOptions, execute_brief

router = APIRouter(prefix="/research")
UTC = timezone.utc
logger = logging.getLogger(__name__)
TRADING_RUN_GRACE = timedelta(minutes=15)


class Schedule(BriefOptions):
    name: str = Field(min_length=1, max_length=30, pattern=r"\S")
    config: ResearchConfig
    repeat: Literal["hourly", "daily", "weekdays", "weekly", "trading_days"]
    time: time
    weekday: int = Field(default=0, ge=0, le=6)
    enabled: bool = True
    timing: Literal["clock", "before_open", "after_close"] = "clock"
    offset_minutes: int = Field(default=30, ge=0, le=180)

    @model_validator(mode="after")
    def validate_universe(self):
        if self.timing != "clock" and self.repeat != "trading_days":
            raise ValueError("按开收盘执行需要选择每交易日")
        if self.timing == "after_close" and self.offset_minutes < close_buffer_minutes(self.config.market):
            raise ValueError("收盘后至少等待 15 分钟，新加坡至少等待 20 分钟")
        if self.workflow != "stock":
            self.symbols = self.universe(self.config)
            if self.workflow in ("watch", "filings", "weekly") and not self.symbols:
                raise ValueError("请添加至少一个自选标的")
            markets = {self.config.market}
            if self.workflow in PRICE_WORKFLOWS and self.config.market in {"SH", "SZ"}:
                markets = {"SH", "SZ"}
            if any(symbol.rsplit(".", 1)[1] not in markets for symbol in self.symbols):
                raise ValueError("标的市场必须与计划市场一致")
        return self


def trading_run_time(plan, day, half_day=False):
    market = plan.config.market
    clock = plan.time.replace(tzinfo=None)
    offset = 0
    if plan.timing == "before_open":
        clock, _ = cash_hours(market, half_day)
        offset = -plan.offset_minutes
    elif plan.timing == "after_close":
        _, clock = cash_hours(market, half_day)
        offset = plan.offset_minutes
    return (datetime.combine(day, clock, tzinfo=market_zone(market)) + timedelta(minutes=offset)).astimezone(UTC)


def next_occurrence(schedule: Schedule, now: datetime) -> str | None:
    if schedule.repeat == "trading_days":
        return None  # The calendar worker confirms these dates asynchronously.
    if schedule.repeat == "hourly":
        # All supported markets use whole-hour offsets, including US daylight saving time.
        utc_now = now.astimezone(UTC)
        candidate = utc_now.replace(minute=schedule.time.minute, second=0, microsecond=0)
        return (candidate if candidate > utc_now else candidate + timedelta(hours=1)).isoformat()
    local = now.astimezone(market_zone(schedule.config.market))
    for offset in range(8):
        day = local.date() + timedelta(days=offset)
        if schedule.repeat == "weekly" and day.weekday() != schedule.weekday:
            continue
        if schedule.repeat == "weekdays" and day.weekday() >= 5:
            continue
        candidate = datetime.combine(day, schedule.time.replace(tzinfo=None), tzinfo=local.tzinfo)
        if candidate > local:
            return candidate.astimezone(UTC).isoformat()
    raise RuntimeError("无法计算下次执行时间")


def initialize_queue():
    """Validate migrated storage without changing historical task states."""
    with connect() as db:
        db.execute(select(Job.id).limit(1))


def as_datetime(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def schedule_payload(body, now=None):
    schedule = Schedule.model_validate(body)
    now = now or datetime.now(UTC)
    config = schedule.config.model_copy(update={"as_of": now.astimezone(market_zone(schedule.config.market)).date()})
    payload = config.model_dump(mode="json")
    if schedule.workflow != "stock":
        payload["_brief"] = BriefOptions.model_validate(schedule.model_dump()).model_dump(mode="json")
    return payload


def translated(operation):
    try:
        return operation()
    except MissingRecord as error:
        raise HTTPException(404, str(error)) from None
    except StateConflict as error:
        raise HTTPException(409, str(error)) from None


@router.post("/tasks", status_code=202)
def create_job(config: ResearchConfig):
    return {"id": JobRepository().create_job(f"{config.symbol} 单股分析", config.model_dump(mode="json"))}


@router.get("/tasks")
def tasks(schedule_id: str | None = None, kind: Literal["manual", "scheduled", "document", "knowledge"] | None = None,
          limit: Annotated[int | None, Query(ge=1, le=100)] = None):
    return {"tasks": JobRepository().list_tasks(schedule_id, kind, limit)}


@router.get("/tasks/{job_id}")
def task_detail(job_id: str):
    return translated(lambda: JobRepository().task_detail(job_id))


@router.delete("/tasks/{job_id}")
def hide_task(job_id: str):
    translated(lambda: JobRepository().hide_task(job_id))
    return {"id": job_id}


@router.post("/tasks/{job_id}/cancel")
def cancel_task(job_id: str):
    return {"id": job_id, "status": translated(lambda: JobRepository().cancel(job_id))}


@router.get("/schedules")
def schedules():
    from src.infrastructure.config import environment
    now = datetime.now(UTC).isoformat()
    result = JobRepository().list_schedules()
    for plan in result:
        if plan["repeat"] == "trading_days" and plan["next_run"] and plan["next_run"] <= now:
            plan["next_run"] = None
    enabled = str(environment().get("RESEARCH_SCHEDULER_ENABLED", "false")).lower() == "true"
    return {"schedules": result, "meta": {"scheduler_enabled": enabled}}


@router.get("/schedules/{schedule_id}/history")
def schedule_history(schedule_id: str):
    return tasks(schedule_id)


@router.post("/schedules", status_code=201)
def create_schedule(schedule: Schedule):
    due = next_occurrence(schedule, datetime.now(UTC)) if schedule.enabled else None
    return {"id": JobRepository().create_schedule(schedule.model_dump(mode="json"), as_datetime(due))}


@router.put("/schedules/{schedule_id}")
def update_schedule(schedule_id: str, schedule: Schedule):
    due = next_occurrence(schedule, datetime.now(UTC)) if schedule.enabled else None
    translated(lambda: JobRepository().update_schedule(schedule_id, schedule.model_dump(mode="json"), as_datetime(due)))
    return {"id": schedule_id}


@router.delete("/schedules/{schedule_id}")
def remove_schedule(schedule_id: str):
    translated(lambda: JobRepository().archive_schedule(schedule_id))
    return {"id": schedule_id}


@router.post("/schedules/{schedule_id}/run", status_code=202)
def run_schedule_now(schedule_id: str):
    return translated(lambda: JobRepository().run_schedule(schedule_id, schedule_payload))


def enqueue_clock_run(db, plan, now):
    if not db.scalar(select(Job.id).where(Job.schedule_id == plan.id, Job.status.in_(["queued", "running"]))):
        payload = schedule_payload(plan.body, now)
        payload["_trigger"] = "clock"
        return JobRepository.enqueue(db, plan.body["name"], payload, plan.id)


def dispatch_due_schedules(now=None):
    now = now or datetime.now(UTC)
    with connect() as db:
        plans = db.scalars(select(StoredSchedule).where(StoredSchedule.archived.is_(False),
            StoredSchedule.next_run <= now, StoredSchedule.body["repeat"].astext != "trading_days",
            StoredSchedule.body["enabled"].as_boolean().is_(True)).with_for_update(skip_locked=True).limit(100)).all()
        for plan in plans:
            enqueue_clock_run(db, plan, now)
            plan.next_run = as_datetime(next_occurrence(Schedule.model_validate(plan.body), now))
            plan.version += 1
    return len(plans)


async def sync_trading_schedules(now, retry_after):
    groups = {}
    with connect() as db:
        pending = db.execute(select(StoredSchedule.id, StoredSchedule.body, StoredSchedule.next_run, StoredSchedule.version).where(
            StoredSchedule.archived.is_(False), (StoredSchedule.next_run.is_(None) | (StoredSchedule.next_run <= now)),
            StoredSchedule.body["repeat"].astext == "trading_days", StoredSchedule.body["enabled"].as_boolean().is_(True))).all()
    for key, body, due, version in pending:
        plan = Schedule.model_validate(body)
        market = "SH" if plan.config.market == "SZ" else plan.config.market
        groups.setdefault(market, []).append((key, body, due, version, plan))

    async def sync_market(market, plans):
        if market in retry_after and now < retry_after[market]:
            return
        zone = market_zone(market)
        today = now.astimezone(zone).date()
        try:
            anchored = any(plan.timing != "clock" for _, _, _, _, plan in plans)
            calendar = await exchange_calendar(market, today, today + timedelta(days=21)) if anchored else {}
            sessions = list(calendar) if anchored else await exchange_sessions(market, today, today + timedelta(days=21))
            if not sessions:
                raise ValueError("未来交易日历为空")
            times = {key: [trading_run_time(plan, day, calendar.get(day, False)) for day in sessions]
                     for key, _, _, _, plan in plans}
        except (RuntimeError, ValueError, TypeError, OSError, TimeoutError):
            retry_after[market] = now + timedelta(minutes=1)
            return
        retry_after.pop(market, None)
        with connect() as db:
            for key, body, due, version, plan in plans:
                stored = db.scalar(select(StoredSchedule).where(StoredSchedule.id == key).with_for_update())
                if stored is None or stored.archived or stored.version != version or stored.next_run != due:
                    continue  # Pause, edit or another scheduler wins while a source request is in flight.
                stored.next_run = next((candidate for candidate in times[key] if candidate > now), None)
                stored.version += 1
                if not due:
                    continue
                if (due in times[key] and due.astimezone(zone).date() == today and now - due <= TRADING_RUN_GRACE):
                    enqueue_clock_run(db, stored, now)

    await asyncio.gather(*(sync_market(market, plans) for market, plans in groups.items()))
