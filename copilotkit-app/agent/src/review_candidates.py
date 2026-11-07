"""Persist the local market review shortlist."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, exists, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from .persistence.models import CandidateObservation, Report, ReviewCandidate

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
        rows = select(ReviewCandidate.symbol, ReviewCandidate.session, ReviewCandidate.benchmark, literal("legacy")).where(
            ~exists(select(CandidateObservation.symbol).where(CandidateObservation.symbol == ReviewCandidate.symbol)))
        db.execute(insert(CandidateObservation).from_select(["symbol", "session", "benchmark", "origin"], rows).on_conflict_do_nothing())


@router.get("")
def list_candidates():
    with connect() as db:
        rows = db.execute(select(ReviewCandidate.symbol, ReviewCandidate.session, ReviewCandidate.benchmark, ReviewCandidate.note,
                                 CandidateObservation.session.label("observed_session"), CandidateObservation.benchmark.label("observed_benchmark"),
                                 CandidateObservation.origin, CandidateObservation.report_id, Report.id.is_not(None).label("report_available"))
            .join(CandidateObservation, CandidateObservation.symbol == ReviewCandidate.symbol)
            .outerjoin(Report, (Report.id == CandidateObservation.report_id) & Report.archived.is_(False))
            .order_by(ReviewCandidate.record_order.desc(), CandidateObservation.session.desc(), CandidateObservation.record_order.desc())).mappings().all()
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
    scope = {"symbol": candidate.symbol, "session": candidate.session.isoformat(), "benchmark": candidate.benchmark}
    with connect() as db:
        db.execute(insert(ReviewCandidate).values(**scope).on_conflict_do_nothing())
        db.execute(insert(CandidateObservation).values(**scope, origin=candidate.origin, report_id=report_id).on_conflict_do_nothing())
    return {"ok": True}


@router.put("/{symbol}")
def update_note(symbol: str, request: CandidateNote):
    with connect() as db:
        cursor = db.execute(update(ReviewCandidate).where(ReviewCandidate.symbol == symbol).values(note=request.note.strip()))
        if not cursor.rowcount:
            raise HTTPException(404, "该标的已移出候选池")
    return {"ok": True}


@router.delete("/{symbol}")
def remove_candidate(symbol: str):
    with connect() as db:
        db.execute(delete(CandidateObservation).where(CandidateObservation.symbol == symbol))
        db.execute(delete(ReviewCandidate).where(ReviewCandidate.symbol == symbol))
    return {"ok": True}
