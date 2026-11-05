"""Persist the local market review shortlist."""
import sqlite3
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from .market_review import MIN_DATE, SHANGHAI, completed_cutoff, mainland_symbol
from .market_sentiment import pool_reference
from .research_store import connect, get_report

router = APIRouter(prefix="/research/review-candidates")


class CandidateRequest(BaseModel):
    symbol: str
    session: date
    benchmark: str
    origin: Literal["sample", "ladder", "follow_through", "industry", "report"] = "sample"
    report_id: UUID | None = None

    @field_validator("symbol", "benchmark")
    @classmethod
    def validate_symbol(cls, value):
        return mainland_symbol(value)

    @model_validator(mode="after")
    def validate_origin(self):
        if (self.origin == "report") != (self.report_id is not None):
            raise ValueError("仅报告观察需要绑定报告编号")
        return self


class CandidateNote(BaseModel):
    note: str = Field(max_length=280)


def initialize_candidates():
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS review_candidates (
                symbol TEXT PRIMARY KEY, session TEXT NOT NULL, benchmark TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS candidate_observations (
                symbol TEXT NOT NULL, session TEXT NOT NULL, benchmark TEXT NOT NULL,
                origin TEXT NOT NULL, report_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (symbol, session, benchmark, origin, report_id)
            );
        """)
        db.execute("""INSERT OR IGNORE INTO candidate_observations (symbol, session, benchmark, origin)
                      SELECT c.symbol, c.session, c.benchmark, 'legacy' FROM review_candidates c
                      WHERE NOT EXISTS (SELECT 1 FROM candidate_observations o WHERE o.symbol=c.symbol)""")


@router.get("")
def list_candidates():
    with connect() as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("""SELECT c.symbol, c.session, c.benchmark, c.note,
                                    o.session AS observed_session, o.benchmark AS observed_benchmark,
                                    o.origin, o.report_id, r.id IS NOT NULL AS report_available
                             FROM review_candidates c JOIN candidate_observations o ON o.symbol=c.symbol
                             LEFT JOIN reports r ON r.id=o.report_id AND r.archived=0
                             ORDER BY c.rowid DESC, o.session DESC, o.rowid DESC""").fetchall()
    candidates = {}
    pool_kinds = {"ladder": "up", "industry": "up", "follow_through": "previous"}
    for row in rows:
        item = candidates.setdefault(row["symbol"], {
            **{key: row[key] for key in ("symbol", "session", "benchmark", "note")}, "observations": [],
        })
        observation = {"session": row["observed_session"], "benchmark": row["observed_benchmark"], "origin": row["origin"]}
        if kind := pool_kinds.get(row["origin"]):
            _, observation["source_url"] = pool_reference(kind, date.fromisoformat(row["observed_session"]))
        if row["report_id"]:
            observation.update(report_id=row["report_id"], report_available=bool(row["report_available"]))
        item["observations"].append(observation)
    return {"candidates": list(candidates.values())}


@router.post("")
def add_candidate(candidate: CandidateRequest):
    now = datetime.now(SHANGHAI)
    if not MIN_DATE <= candidate.session <= completed_cutoff(now.date(), now):
        raise HTTPException(422, "请选择已收盘的观察日期")
    report_id = str(candidate.report_id) if candidate.report_id else ""
    if report_id:
        report = get_report(report_id)
        if not report:
            raise HTTPException(404, "来源报告已归档或不存在")
        session = max((bar["date"] for bar in (report.get("evidence") or {}).get("bars", [])
                       if (bar.get("volume") or 0) > 0 and bar["date"] <= report["as_of"]), default="")
        if (report.get("workflow") or report["status"] not in {"complete", "partial"} or report["symbol"] != candidate.symbol
                or report.get("config", {}).get("benchmark") != candidate.benchmark or session != candidate.session.isoformat()):
            raise HTTPException(422, "观察范围与来源报告不一致")
    scope = (candidate.symbol, candidate.session.isoformat(), candidate.benchmark)
    with connect() as db:
        db.execute(
            "INSERT INTO review_candidates (symbol,session,benchmark) VALUES (?,?,?) ON CONFLICT(symbol) DO NOTHING",
            scope,
        )
        db.execute("""INSERT INTO candidate_observations (symbol, session, benchmark, origin, report_id)
                      VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING""", (*scope, candidate.origin, report_id))
    return {"ok": True}


@router.put("/{symbol}")
def update_note(symbol: str, request: CandidateNote):
    with connect() as db:
        cursor = db.execute("UPDATE review_candidates SET note=? WHERE symbol=?", (request.note.strip(), symbol))
        if not cursor.rowcount:
            raise HTTPException(404, "该标的已移出候选池")
    return {"ok": True}


@router.delete("/{symbol}")
def remove_candidate(symbol: str):
    with connect() as db:
        db.execute("DELETE FROM candidate_observations WHERE symbol=?", (symbol,))
        db.execute("DELETE FROM review_candidates WHERE symbol=?", (symbol,))
    return {"ok": True}
