"""Persistent local research queue and schedule management."""
import asyncio
import json
import logging
import sqlite3
from datetime import datetime, time, timedelta, timezone
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import Field, model_validator

from .research_data import cash_hours, close_buffer_minutes, exchange_calendar, exchange_sessions, market_zone
from .research_models import ResearchConfig
from .research_store import connect, get_report
from .research_workflow import execute_research
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
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS schedules (id TEXT PRIMARY KEY, body TEXT NOT NULL, next_run TEXT);
            CREATE TABLE IF NOT EXISTS hidden_tasks (id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, config TEXT NOT NULL, schedule_id TEXT,
                status TEXT NOT NULL, created_at TEXT NOT NULL, error TEXT
            );
        """)
        for (job_id,) in db.execute("SELECT id FROM jobs WHERE status='running'").fetchall():
            row = db.execute("SELECT body FROM reports WHERE id=?", (job_id,)).fetchone()
            report = json.loads(row[0]) if row else None
            status = report["status"] if report else "running"
            error = None
            if status == "running":
                status, error = "failed", "服务重启，任务中断"
                if report:
                    report["status"] = status
                    db.execute("UPDATE reports SET body=? WHERE id=?", (json.dumps(report, ensure_ascii=False), job_id))
            db.execute("UPDATE jobs SET status=?, error=? WHERE id=?", (status, error, job_id))


def enqueue(db, name, config, schedule_id=None, *, brief=None, trigger=None):
    job_id = str(uuid4())
    payload = config.model_dump(mode="json")
    if brief:
        payload["_brief"] = brief.model_dump(mode="json")
    if trigger:
        payload["_trigger"] = trigger
    db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,NULL)", (
        job_id, name, json.dumps(payload, ensure_ascii=False), schedule_id, "queued", datetime.now(UTC).isoformat(),
    ))
    return job_id


def enqueue_schedule(db, key, schedule, now, trigger):
    config = schedule.config.model_copy(update={"as_of": now.astimezone(market_zone(schedule.config.market)).date()})
    brief = BriefOptions.model_validate(schedule.model_dump()) if schedule.workflow != "stock" else None
    return enqueue(db, schedule.name, config, key, brief=brief, trigger=trigger)


@router.post("/tasks", status_code=202)
def create_job(config: ResearchConfig):
    with connect() as db:
        return {"id": enqueue(db, f"{config.symbol} 单股分析", config)}


@router.get("/tasks")
def tasks(schedule_id: str | None = None, kind: Literal["manual", "scheduled"] | None = None,
          limit: Annotated[int | None, Query(ge=1, le=100)] = None):
    with connect() as db:
        query = "SELECT id,name,config,schedule_id,status,created_at,error FROM jobs"
        clauses, parameters = [], []
        if schedule_id:
            clauses.append("schedule_id=?")
            parameters.append(schedule_id)
        else:
            clauses.append("id NOT IN (SELECT id FROM hidden_tasks)")
        if kind:
            clauses.append("schedule_id IS NULL" if kind == "manual" else "schedule_id IS NOT NULL")
        rows = db.execute("SELECT job.*, report.id, json_extract(report.body,'$.assessment.summary') FROM (" +
                          query + " WHERE " + " AND ".join(clauses) + " ORDER BY created_at DESC LIMIT ?) AS job "
                          "LEFT JOIN reports AS report ON report.id=job.id AND report.archived=0",
                          (*parameters, limit or -1)).fetchall()
        legacy = [] if schedule_id or kind == "scheduled" else db.execute("""
            SELECT id, json_extract(body,'$.symbol'), json_extract(body,'$.status'), json_extract(body,'$.created_at')
            FROM reports WHERE archived=0 AND id NOT IN (SELECT id FROM jobs)
                AND id NOT IN (SELECT id FROM hidden_tasks)
            ORDER BY json_extract(body,'$.created_at') DESC LIMIT ?
        """, (limit or -1,)).fetchall()
    result = []
    for job_id, name, config, plan_id, status, created_at, error, report_id, summary in rows:
        payload = json.loads(config)
        result.append({"id": job_id, "name": name, "symbol": payload["symbol"], "kind": "scheduled" if plan_id else "manual",
                       "schedule_id": plan_id, "trigger": payload.get("_trigger"), "managed": True,
                       "summary": summary,
                       "status": status, "created_at": created_at, "error": error,
                       "report_id": report_id})
    for report_id, symbol, status, created_at in legacy:
        result.append({"id": report_id, "name": f"{symbol} 单股分析", "symbol": symbol,
                       "kind": "manual", "status": status, "created_at": created_at, "report_id": report_id})
    return {"tasks": sorted(result, key=lambda item: item["created_at"], reverse=True)[:limit]}


@router.get("/tasks/{job_id}")
def task_detail(job_id: str):
    with connect() as db:
        row = db.execute("SELECT name,config,status,error FROM jobs WHERE id=?", (job_id,)).fetchone()
    report = get_report(job_id)
    if row is None:
        if report is None:
            raise HTTPException(404, "任务不存在")
        name, payload, status, error = f"{report['symbol']} 单股分析", report["config"], report["status"], None
    else:
        name, config, status, error = row
        payload = json.loads(config)
    return {
        "id": job_id, "name": name, "status": status, "error": error, "config": payload,
        "workflow": (payload.get("_brief") or {}).get("workflow"),
        "report_id": report["id"] if report else None,
        "stages": report["stages"] if report else [],
        "elapsed_seconds": report["elapsed_seconds"] if report else 0,
        "has_assessment": bool(report and report.get("assessment")),
    }


@router.delete("/tasks/{job_id}")
def hide_task(job_id: str):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            report = db.execute("SELECT body FROM reports WHERE id=? AND archived=0", (job_id,)).fetchone()
            if report is None:
                raise HTTPException(404, "任务不存在")
            status = json.loads(report[0])["status"]
        else:
            status = row[0]
        if status not in {"complete", "partial", "failed", "cancelled"}:
            raise HTTPException(409, "请等任务结束后再删除执行记录。")
        db.execute("INSERT OR IGNORE INTO hidden_tasks VALUES (?)", (job_id,))
    return {"id": job_id}


@router.get("/schedules")
def schedules():
    now = datetime.now(UTC).isoformat()
    with connect() as db:
        result = []
        for key, body, due in db.execute("SELECT id,body,next_run FROM schedules ORDER BY rowid DESC"):
            plan = json.loads(body)
            if plan["repeat"] == "trading_days" and due and due <= now:
                due = None
            result.append({"id": key, **plan, "next_run": due})
    return {"schedules": result}


@router.get("/schedules/{schedule_id}/history")
def schedule_history(schedule_id: str):
    return tasks(schedule_id)


@router.post("/schedules", status_code=201)
def create_schedule(schedule: Schedule):
    schedule_id = str(uuid4())
    with connect() as db:
        db.execute("INSERT INTO schedules VALUES (?,?,?)", (schedule_id, schedule.model_dump_json(),
                   next_occurrence(schedule, datetime.now(UTC)) if schedule.enabled else None))
    return {"id": schedule_id}


@router.put("/schedules/{schedule_id}")
def update_schedule(schedule_id: str, schedule: Schedule):
    with connect() as db:
        cursor = db.execute("UPDATE schedules SET body=?, next_run=? WHERE id=?", (schedule.model_dump_json(),
                            next_occurrence(schedule, datetime.now(UTC)) if schedule.enabled else None, schedule_id))
        if cursor.rowcount == 0:
            raise HTTPException(404, "定时任务不存在")
    return {"id": schedule_id}


@router.delete("/schedules/{schedule_id}")
def remove_schedule(schedule_id: str):
    with connect() as db:
        db.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))
    return {"id": schedule_id}


@router.post("/schedules/{schedule_id}/run", status_code=202)
def run_schedule_now(schedule_id: str):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT body FROM schedules WHERE id=?", (schedule_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "定时任务不存在")
        active = db.execute(
            "SELECT id FROM jobs WHERE schedule_id=? AND status IN ('queued','running')",
            (schedule_id,),
        ).fetchone()
        if active:
            return {"id": active[0], "existing": True}
        schedule = Schedule.model_validate_json(row[0])
        return {"id": enqueue_schedule(db, schedule_id, schedule, datetime.now(UTC), "manual"), "existing": False}


def claim_jobs(capacity):
    now = datetime.now(UTC)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for key, body in db.execute("SELECT id,body FROM schedules WHERE next_run <= ? AND json_extract(body,'$.repeat') != 'trading_days'",
                                    (now.isoformat(),)).fetchall():
            schedule = Schedule.model_validate_json(body)
            enqueue_clock_run(db, key, schedule, now)
            db.execute("UPDATE schedules SET next_run=? WHERE id=?", (next_occurrence(schedule, now), key))
        rows = db.execute("SELECT id,config FROM jobs WHERE status='queued' ORDER BY created_at LIMIT ?", (capacity,)).fetchall()
        db.executemany("UPDATE jobs SET status='running' WHERE id=?", [(job_id,) for job_id, _ in rows])
    return rows


def enqueue_clock_run(db, key, schedule, now):
    if not db.execute("SELECT 1 FROM jobs WHERE schedule_id=? AND status IN ('queued','running')", (key,)).fetchone():
        enqueue_schedule(db, key, schedule, now, "clock")


async def sync_trading_schedules(now, retry_after):
    groups = {}
    with connect() as db:
        pending = db.execute("""
            SELECT id,body,next_run FROM schedules WHERE (next_run IS NULL OR next_run <= ?)
                AND json_extract(body,'$.repeat') = 'trading_days' AND json_extract(body,'$.enabled') = 1
        """, (now.isoformat(),)).fetchall()
    for key, body, due in pending:
        plan = Schedule.model_validate_json(body)
        market = "SH" if plan.config.market == "SZ" else plan.config.market
        groups.setdefault(market, []).append((key, body, due, plan))

    async def sync_market(market, plans):
        if market in retry_after and now < retry_after[market]:
            return
        zone = market_zone(market)
        today = now.astimezone(zone).date()
        try:
            anchored = any(plan.timing != "clock" for _, _, _, plan in plans)
            calendar = await exchange_calendar(market, today, today + timedelta(days=21)) if anchored else {}
            sessions = list(calendar) if anchored else await exchange_sessions(market, today, today + timedelta(days=21))
            if not sessions:
                raise ValueError("未来交易日历为空")
            times = {key: [trading_run_time(plan, day, calendar.get(day, False)) for day in sessions]
                     for key, _, _, plan in plans}
        except (RuntimeError, ValueError, TypeError, OSError, TimeoutError):
            retry_after[market] = now + timedelta(minutes=1)
            return
        retry_after.pop(market, None)
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for key, body, due, plan in plans:
                next_run = next((candidate.isoformat() for candidate in times[key] if candidate > now), None)
                # A user edit or pause made during the calendar request wins.
                updated = db.execute("UPDATE schedules SET next_run=? WHERE id=? AND body=? AND next_run IS ?",
                                     (next_run, key, body, due))
                if not updated.rowcount or not due:
                    continue
                scheduled = datetime.fromisoformat(due)
                if (scheduled in times[key] and scheduled.astimezone(zone).date() == today
                        and now - scheduled <= TRADING_RUN_GRACE):
                    enqueue_clock_run(db, key, plan, now)

    await asyncio.gather(*(sync_market(market, plans) for market, plans in groups.items()))


async def run_trading_scheduler():
    retry_after = {}
    while True:
        try:
            await sync_trading_schedules(datetime.now(UTC), retry_after)
        except sqlite3.OperationalError:
            logger.exception("Trading calendar scheduler could not access SQLite; will retry")
        await asyncio.sleep(2)


async def run_job(job_id, raw_config):
    error = None
    try:
        payload = json.loads(raw_config)
        config = ResearchConfig.model_validate(payload)
        if payload.get("_brief"):
            report = await execute_brief(config, BriefOptions.model_validate(payload["_brief"]), job_id)
        else:
            report = await execute_research(config, report_id=job_id)
        status = report["status"]
    except asyncio.CancelledError:
        status, error = "cancelled", "服务停止，任务中断"
        raise
    except Exception as exc:
        status, error = "failed", f"研究执行失败（{type(exc).__name__}）"
    finally:
        with connect() as db:
            db.execute("UPDATE jobs SET status=?,error=? WHERE id=?", (status, error, job_id))


async def run_queue():
    active = set()
    calendar = asyncio.create_task(run_trading_scheduler())
    try:
        while True:
            active = {task for task in active if not task.done()}
            try:
                claimed = claim_jobs(3 - len(active))
            except sqlite3.OperationalError:
                logger.exception("Research queue could not access SQLite; will retry")
                claimed = []
            for job_id, config in claimed:
                active.add(asyncio.create_task(run_job(job_id, config)))
            await asyncio.sleep(2)
    finally:
        for task in active | {calendar}:
            task.cancel()
        await asyncio.gather(*active, calendar, return_exceptions=True)
