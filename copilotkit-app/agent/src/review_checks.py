"""Persist a research condition and verify the next exchange session."""
import asyncio
import json
import logging
import sqlite3
from datetime import date, datetime, time, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from .market_review import MIN_DATE, SHANGHAI, completed_cutoff, mainland_symbol, review_row
from .research_data import candles, exchange_sessions
from .research_models import ResearchConfig
from .research_store import connect, get_report

router = APIRouter(prefix="/research")
logger = logging.getLogger(__name__)
CALENDAR_URL = "https://open.longbridge.com/docs/market/trade-days"
DATA_FAILURES = (RuntimeError, ValueError, TimeoutError, OSError, TypeError, KeyError, AttributeError)
active_checks: set[str] = set()


class ReportOrigin(BaseModel):
    report_id: UUID
    condition_index: int = Field(ge=0)


class CheckRequest(BaseModel):
    symbol: str
    benchmark: str
    baseline: date
    metric: Literal["day_pct", "relative_pct", "volume_ratio"]
    direction: Literal["gte", "lte"]
    threshold: float = Field(ge=-100, le=100, allow_inf_nan=False)
    note: str = Field(default="", max_length=160)
    report_origin: ReportOrigin | None = None

    @field_validator("symbol", "benchmark")
    @classmethod
    def validate_symbol(cls, value):
        return mainland_symbol(value)


def check_store(db):
    db.execute("CREATE TABLE IF NOT EXISTS review_checks (id TEXT PRIMARY KEY, body TEXT NOT NULL, settled INTEGER NOT NULL DEFAULT 0)")


def confirmed_report_origin(request):
    origin = request.report_origin
    report = get_report(str(origin.report_id))
    if report is None:
        raise HTTPException(404, "来源报告已归档或不存在。")
    conditions = (report.get("assessment") or {}).get("invalidation_conditions") or []
    if (report.get("workflow") or report["status"] not in {"complete", "partial"}
            or origin.condition_index >= len(conditions)):
        raise HTTPException(422, "该报告条件尚不可用于收盘验证。")
    condition = conditions[origin.condition_index]
    if not isinstance(condition, str) or not condition.strip():
        raise HTTPException(422, "找不到有效的报告条件。")
    dates = [bar["date"] for bar in (report.get("evidence") or {}).get("bars", [])
             if (bar.get("volume") or 0) > 0 and bar["date"] <= report["as_of"]]
    if request.symbol != report["symbol"] or request.baseline.isoformat() != max(dates, default=""):
        raise HTTPException(422, "验证标的或基线与来源报告的最近有效交易日不一致。")
    return {**origin.model_dump(mode="json"), "condition": condition[:1500]}


@router.get("/review-checks")
def list_checks():
    with connect() as db:
        check_store(db)
        rows = db.execute("SELECT body FROM review_checks ORDER BY rowid DESC").fetchall()
    return {"checks": [json.loads(row[0]) for row in rows]}


@router.post("/review-checks", status_code=201)
def create_check(request: CheckRequest):
    now = datetime.now(SHANGHAI)
    if not MIN_DATE <= request.baseline <= completed_cutoff(now.date(), now):
        raise HTTPException(422, "请选择已完成的基准交易日")
    if request.metric == "volume_ratio" and request.threshold < 0:
        raise HTTPException(422, "量比阈值必须大于或等于 0")
    if request.metric == "relative_pct" and request.symbol == request.benchmark:
        raise HTTPException(422, "相对涨跌需要选择不同的基准")
    entry = {**request.model_dump(mode="json", exclude={"report_origin"}), "id": str(uuid4()), "created_at": now.isoformat(),
             "result": None, "note": request.note.strip(), "next_attempt_at": now.isoformat(),
             "message": "等待后台确认目标交易日。"}
    if request.report_origin is not None:
        entry["report_origin"] = confirmed_report_origin(request)
    with connect() as db:
        check_store(db)
        db.execute("INSERT INTO review_checks (id, body) VALUES (?,?)", (entry["id"], json.dumps(entry, ensure_ascii=False)))
    return entry


@router.delete("/review-checks/{check_id}")
def delete_check(check_id: UUID):
    with connect() as db:
        check_store(db)
        db.execute("DELETE FROM review_checks WHERE id=?", (str(check_id),))
    return {"id": str(check_id)}


@router.post("/review-checks/{check_id}/verify")
async def verify_check(check_id: UUID):
    return await run_check(str(check_id), datetime.now(SHANGHAI), "manual")


async def run_check(key, now, trigger):
    with connect() as db:
        check_store(db)
        row = db.execute("SELECT body,settled FROM review_checks WHERE id=?", (key,)).fetchone()
    if row is None:
        raise HTTPException(404, "找不到这条验证条件")
    entry = json.loads(row[0])
    if row[1] or key in active_checks:
        return entry
    active_checks.add(key)
    try:
        await evaluate_check(entry, now, trigger)
        with connect() as db:
            updated = db.execute("UPDATE review_checks SET body=?,settled=? WHERE id=? AND settled=0",
                                 (json.dumps(entry, ensure_ascii=False), int(entry["result"] is not None), key))
            if not updated.rowcount:
                latest = db.execute("SELECT body FROM review_checks WHERE id=?", (key,)).fetchone()
                if latest is None:
                    raise HTTPException(404, "这条验证条件已删除")
                return json.loads(latest[0])
        return entry
    finally:
        active_checks.discard(key)


async def evaluate_check(entry, now, trigger):
    baseline = date.fromisoformat(entry["baseline"])
    entry["last_checked_at"] = now.isoformat()
    target = date.fromisoformat(entry["target_session"]) if entry.get("target_session") else None

    def wait(message, *, retry_at=None, stop=False):
        deadline = target + timedelta(days=7) if target else baseline + timedelta(days=35)
        retry_at = retry_at or now + timedelta(minutes=15)
        will_retry = not stop and retry_at.date() <= deadline
        entry["next_attempt_at"] = retry_at.isoformat() if will_retry else None
        entry["message"] = message

    try:
        sessions = await exchange_sessions("SH", baseline, baseline + timedelta(days=28))
    except DATA_FAILURES:
        wait("暂时无法核对沪深交易日历。")
        return
    if not sessions:
        wait("交易日历未返回有效日期。")
        return
    if baseline not in sessions:
        entry["target_session"] = None
        wait("基线日期不在沪深交易日历中，请从已收盘的复盘样本重新保存条件。", stop=True)
        return
    target = next((day for day in sessions if day > baseline), None)
    if target is None:
        wait("交易日历暂未确认基线后的下一个交易日。")
        return
    session = target.isoformat()
    entry["target_session"] = session
    if target > completed_cutoff(now.date(), now):
        wait("等待目标交易日收盘。", retry_at=datetime.combine(target, time(15, 15), SHANGHAI))
        return

    async def fetch(symbol):
        config = ResearchConfig(symbol=symbol, market=symbol.split(".")[1], as_of=target, peers=[])
        return await asyncio.wait_for(candles(symbol, config, lookback_days=(target - baseline).days + 50,
                                              required_sessions=(entry["baseline"], session)), timeout=20)

    try:
        if entry["symbol"] == entry["benchmark"]:
            benchmark_data = data = await fetch(entry["benchmark"])
        else:
            benchmark_data, data = await asyncio.gather(fetch(entry["benchmark"]), fetch(entry["symbol"]))
    except DATA_FAILURES:
        wait("行情暂不可用，条件仍待核对。")
        return

    benchmark = review_row(entry["benchmark"], benchmark_data, session, entry["baseline"])
    observed = review_row(entry["symbol"], data, session, entry["baseline"])
    if not benchmark or not observed:
        missing = "标的及基准" if not benchmark and not observed else "标的" if not observed else "基准"
        wait(f"{missing}在基线或目标日 {session} 缺少有效成交日线。")
        return
    value = (round(observed["day_pct"] - benchmark["day_pct"], 4)
             if entry["metric"] == "relative_pct" else observed[entry["metric"]])
    if value is None:
        wait("样本不足 20 个有成交日，暂时无法计算量比。")
        return
    target_start = datetime.combine(target, time(9, 15), SHANGHAI)
    entry.update(message=None, next_attempt_at=None)
    entry["result"] = {
        "session": session, "value": value, "verified_at": now.isoformat(),
        "met": value >= entry["threshold"] if entry["direction"] == "gte" else value <= entry["threshold"],
        "retrospective": datetime.fromisoformat(entry["created_at"]) >= target_start,
        "observation": observed, "benchmark": benchmark, "trigger": trigger, "calendar_source": CALENDAR_URL,
    }


async def run_due_checks(now):
    with connect() as db:
        check_store(db)
        pending = db.execute("""
            SELECT id FROM review_checks WHERE settled=0 AND (
                json_type(body,'$.next_attempt_at') IS NULL OR json_extract(body,'$.next_attempt_at') <= ?
            ) ORDER BY json_extract(body,'$.next_attempt_at'), rowid LIMIT 4
        """, (now.isoformat(),)).fetchall()
    for (key,) in pending:
        try:
            await run_check(key, now, "auto")
        except HTTPException as exc:
            if exc.status_code != 404:
                raise


async def run_review_checks():
    while True:
        try:
            await run_due_checks(datetime.now(SHANGHAI))
        except sqlite3.OperationalError:
            logger.exception("Review check scheduler could not access SQLite; will retry")
        await asyncio.sleep(5)
