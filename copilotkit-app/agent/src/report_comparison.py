"""Compare saved research with an explicit, reproducible price window."""
import math
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .research_store import get_report

router = APIRouter(prefix="/research")


class ComparisonRequest(BaseModel):
    report_ids: list[UUID] = Field(min_length=2, max_length=2)
    points: Literal[5, 20, 60] = 20


def market_group(symbol):
    market = symbol.rsplit(".", 1)[-1]
    return "CN" if market in {"SH", "SZ"} else market if market in {"HK", "US", "SG"} else None


def valid_bars(report):
    """Do not choose arbitrarily between duplicate dates or bridge missing bars."""
    rows = {}
    duplicates = set()
    skipped = 0
    for bar in report["evidence"].get("bars", []):
        try:
            session = bar["date"]
            if date.fromisoformat(session).isoformat() != session or session > report["as_of"]:
                raise ValueError()
            close, volume = bar["close"], bar.get("volume")
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) or
                   not math.isfinite(value) or value <= 0 for value in (close, volume)):
                raise ValueError()
            if session in rows:
                duplicates.add(session)
            rows[session] = close
        except (KeyError, TypeError, ValueError):
            skipped += 1
    for session in duplicates:
        del rows[session]
    return rows, skipped + len(duplicates)


def aligned_prices(reports, points):
    parsed = [valid_bars(report) for report in reports]
    dates = sorted(set(parsed[0][0]) & set(parsed[1][0]))
    selected = dates[-points:]
    gaps = []
    if len(selected) < points:
        gaps.append(f"请求最近 {points} 个共同成交日，报告实际仅共同覆盖 {len(selected)} 日。")
    if len(selected) < 2:
        gaps.append("至少需要两个共同成交日才能计算同区间价格变化。")
    series = []
    stats = []
    for index, (report, (bars, skipped)) in enumerate(zip(reports, parsed)):
        latest = max(bars, default=None)
        if skipped:
            gaps.append(f"{report['symbol']} 已排除 {skipped} 条无效或重复日期记录。")
        if latest and selected and latest != selected[-1]:
            gaps.append(f"{report['symbol']} 最新有效行情为 {latest}，对照只到双方共同覆盖的 {selected[-1]}。")
        sources = [source["id"] for source in report["evidence"]["sources"]
                   if source.get("kind") == "prices" and source.get("symbol") == report["symbol"]]
        if not sources:
            gaps.append(f"{report['symbol']} 保存的日线未关联到带标的代码的价格来源编号。")
        enough = len(selected) >= 2
        start, end = (bars[selected[0]], bars[selected[-1]]) if enough else (None, None)
        stats.append({"report_id": report["id"], "symbol": report["symbol"], "last_session": latest,
                      "valid_sessions": len(bars), "source_ids": sources,
                      "start_close": start, "end_close": end,
                      "change_pct": round((end / start - 1) * 100, 4) if enough else None})
    if len(selected) >= 2:
        series = [{"date": session, **{f"price_{index}": round(bars[session] / bars[selected[0]] * 100, 6)
                                      for index, (bars, _) in enumerate(parsed)}} for session in selected]
    return {"requested_points": points, "common_sessions": len(dates), "used_sessions": len(selected),
            "start_session": selected[0] if len(selected) >= 2 else None,
            "end_session": selected[-1] if len(selected) >= 2 else None,
            "series": series, "stats": stats, "gaps": gaps}


@router.post("/report-comparisons")
def compare_reports(request: ComparisonRequest):
    if request.report_ids[0] == request.report_ids[1]:
        raise HTTPException(422, "请选择两份不同的报告。")
    reports = [get_report(str(report_id)) for report_id in request.report_ids]
    if any(report is None for report in reports):
        raise HTTPException(404, "其中一份报告已归档或不存在，请返回报告库重新选择。")
    for report in reports:
        evidence = report.get("evidence")
        config = report.get("config")
        if report.get("workflow") or report.get("status") not in {"complete", "partial"}:
            raise HTTPException(422, "仅支持已完成或部分完成的单股报告。")
        if not isinstance(config, dict) or not isinstance(config.get("analysts"), list) or not isinstance(evidence, dict) or not all(
                isinstance(evidence.get(key), list) for key in ("bars", "sources", "gaps")):
            raise HTTPException(422, "报告记录缺少研究范围或证据，暂时无法对照。")
        try:
            date.fromisoformat(report["as_of"])
            if not market_group(report["symbol"]):
                raise ValueError()
        except (KeyError, TypeError, ValueError, AttributeError):
            raise HTTPException(422, "报告缺少有效的市场或截止日期。")
    historical = reports[0]["symbol"] == reports[1]["symbol"]
    if not historical and (reports[0]["as_of"] != reports[1]["as_of"] or
                           market_group(reports[0]["symbol"]) != market_group(reports[1]["symbol"])):
        raise HTTPException(422, "双标的对照需要相同的截止日期和市场（沪深可互相对照）。")
    reports.sort(key=(lambda report: (report["as_of"], report.get("created_at", ""))) if historical
                 else (lambda report: report["symbol"]))
    return {"mode": "history" if historical else "cross_section", "reports": reports,
            "prices": None if historical else aligned_prices(reports, request.points)}
