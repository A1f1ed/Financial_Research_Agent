"""Read Eastmoney limit pools and corroborate each dated snapshot independently."""
import asyncio
import re
import statistics
from collections import Counter
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException

from .a_share_events import SHANGHAI, fetch_eastmoney, number
from .market_review import MIN_DATE, completed_cutoff
from .research_data import tencent_candles

router = APIRouter(prefix="/research")
POOLS = {
    "up": ("涨停池", "getTopicZTPool", "fbt:asc"),
    "broken": ("炸板池", "getTopicZBPool", "fbt:asc"),
    "down": ("跌停池", "getTopicDTPool", "fund:asc"),
}


def parse_pool(payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or payload.get("rc") != 0:
        raise ValueError("来源未返回完整的行情池")
    total, rows = data.get("tc"), data.get("pool")
    if type(total) is not int or not isinstance(rows, list) or total != len(rows):
        raise ValueError("来源总数与返回记录不一致")
    normalized = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("c"), str) or not re.fullmatch(r"[0-9]{6}", row["c"]):
            raise ValueError("行情池证券代码异常")
        market_id = row.get("m")
        if type(market_id) is not int:
            raise ValueError("行情池市场编号异常")
        market = {0: "SZ", 1: "SH"}.get(market_id)
        code = row["c"]
        close, change = number(row.get("p")), number(row.get("zdp"))
        if code in seen or close is None or close <= 0 or change is None:
            raise ValueError("行情池含重复证券或无效行情")
        seen.add(code)
        days = row.get("lbc")
        normalized.append({
            "code": code, "market_id": market_id, "symbol": f"{code}.{market}" if market else None,
            "name": str(row.get("n") or code)[:60], "close": close / 1000, "change": change,
            "days": days if type(days) is int and days > 0 else None,
            "industry": str(row.get("hybk") or "").strip()[:60],
        })
    return {"rows": normalized, "provider_date": str(data.get("qdate", ""))}


def corroborated(sample, bars, session):
    dates = [row for row in bars if row["date"] <= session.isoformat() and row["volume"] > 0]
    if len(dates) < 2 or dates[-1]["date"] != session.isoformat():
        return False
    previous, current = dates[-2]["close"], dates[-1]["close"]
    move = (current / previous - 1) * 100
    return abs(current - sample["close"]) < 0.0006 and abs(move - sample["change"]) <= 0.15 and abs(move) >= 0.5


def pool_reference(kind, session):
    label, endpoint, sort = ("昨涨停股次日行情", "getYesterdayZTPool", "zs:desc") if kind == "previous" else POOLS[kind]
    params = urlencode({"ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt", "Pageindex": 0,
                        "pagesize": 10000, "sort": sort, "date": session.strftime("%Y%m%d")})
    return label, f"https://push2ex.eastmoney.com/{endpoint}?{params}"


async def read_pool(kind, session):
    label, source = pool_reference(kind, session)
    query_day = session.strftime("%Y%m%d")
    try:
        data = await fetch_eastmoney(source, parse_pool, cache_key=f"market-pool:v2:{source}")
        rows = data["rows"]
        if not rows:
            # A historical empty response carries no row to date independently.
            if data["provider_date"] != query_day:
                raise ValueError("空池未能确认所属交易日")
            return {"label": label, "count": 0, "sample": [], "rows": [], "source": source}
        candidates = [row for row in rows if row["symbol"] and abs(row["change"]) >= 0.5]
        if not candidates:
            raise ValueError("没有可用的沪深交叉核对样本")
        selected = [candidates[0], candidates[-1]] if len(candidates) > 1 else candidates
        independent = await asyncio.gather(*(tencent_candles(row["symbol"], session - timedelta(days=21), session) for row in selected))
        if not all(corroborated(row, bars, session) for row, (bars, _) in zip(selected, independent)):
            raise ValueError("抽样日线与来源池记录未能对齐")
        sample = [{"symbol": row["symbol"], "close": row["close"], "source": url}
                  for row, (_, url) in zip(selected, independent)]
        return {"label": label, "count": len(rows), "sample": sample, "rows": rows, "source": source}
    except (ValueError, TypeError, OSError, KeyError, IndexError, TimeoutError):
        return {"label": label, "count": None, "sample": [], "rows": [], "source": source,
                "reason": "未取得可确认所属交易日的完整数据"}


@router.get("/market-sentiment")
async def market_sentiment(session: date):
    now = datetime.now(SHANGHAI)
    if not MIN_DATE <= session <= completed_cutoff(now.date(), now):
        raise HTTPException(422, "请选择已收盘的交易日")
    pools = dict(zip(POOLS, await asyncio.gather(*(read_pool(kind, session) for kind in POOLS))))
    up, broken = pools["up"], pools["broken"]
    up_rows = up["rows"]
    industries = Counter(row["industry"] for row in up_rows if row["industry"])
    ladder = Counter(row["days"] for row in up_rows if row["days"])
    leaders = sorted((row for row in up_rows if row["days"] and row["days"] > 1), key=lambda row: -row["days"])[:8]
    rate = None
    if up["count"] is not None and broken["count"] is not None:
        total = up["count"] + broken["count"]
        if total and not ({row["code"] for row in up_rows} & {row["code"] for row in broken["rows"]}):
            rate = round(broken["count"] / total * 100, 2)
    for pool in pools.values():
        del pool["rows"]
    return {"session": session, "pools": pools, "break_rate": rate, "leaders": leaders,
            "ladder": [{"days": days, "count": ladder[days]} for days in sorted(ladder, reverse=True)],
            "industries": [{"name": name, "count": count} for name, count in industries.most_common(6)]}


def industry_history(sessions, pools):
    groups = []
    totals = Counter()
    days = []
    for session, pool in zip(sessions, pools):
        industries = {}
        for row in pool["rows"]:
            if row["industry"]:
                industries.setdefault(row["industry"], []).append({key: row[key] for key in ("code", "symbol", "name", "days")})
        counts = {name: len(rows) for name, rows in industries.items()}
        totals.update(counts)
        groups.append(industries)
        days.append({"session": session, "total": pool["count"], "classified": sum(counts.values()),
                     "source": pool["source"], "sample": pool["sample"]})
    names = sorted(totals, key=lambda name: (-len(groups[-1].get(name, [])), -totals[name], name))
    return {"days": days, "industries": [
        {"name": name, "members": [group.get(name, []) if day["total"] is not None else None
                                   for group, day in zip(groups, days)]}
        for name in names
    ]}


@router.get("/market-industry-history")
async def market_industry_history(session: date):
    now = datetime.now(SHANGHAI)
    if not MIN_DATE <= session <= completed_cutoff(now.date(), now):
        raise HTTPException(422, "请选择已收盘的交易日")
    try:
        bars, source = await tencent_candles("510300.SH", session - timedelta(days=30), session)
    except (ValueError, TypeError, OSError, KeyError, IndexError, TimeoutError):
        raise HTTPException(503, "参考日线暂不可用，无法核对交易日期")
    sessions = [date.fromisoformat(bar["date"]) for bar in bars if bar["volume"] > 0][-5:]
    if not sessions or sessions[-1] != session:
        raise HTTPException(422, "参考日线未确认所选日期为有成交的交易日")
    pools = await asyncio.gather(*(read_pool("up", day) for day in sessions))
    return {"calendar_source": source, **industry_history(sessions, pools)}


def follow_through_summary(prior, observed, current):
    cohort = {row["code"]: row for row in prior["rows"]}
    def in_cohort(row):
        baseline = cohort.get(row["code"])
        return baseline is not None and row["market_id"] == baseline["market_id"]

    matched = [row for row in observed["rows"] if in_cohort(row)]
    result = {"cohort_count": prior["count"], "observed_count": len(matched) if observed["count"] is not None else None,
              "up": None, "flat": None, "down": None, "median": None, "resealed": None, "reseal_rate": None,
              "groups": [], "movers": []}
    if prior["count"] is None:
        return {**result, "observed_count": None}
    if current["count"] is not None:
        result["resealed"] = sum(in_cohort(row) for row in current["rows"])
        if cohort:
            result["reseal_rate"] = round(result["resealed"] / len(cohort) * 100, 2)
    if observed["count"] is None:
        return result
    changes = [row["change"] for row in matched]
    result.update(up=sum(value > 0 for value in changes), flat=sum(value == 0 for value in changes),
                  down=sum(value < 0 for value in changes))
    if changes:
        result["median"] = round(statistics.median(changes), 2)
    for label, ranks in (("昨日首板", [1]), ("昨日二板", [2]), ("昨日三板及以上", range(3, 10000))):
        size = sum(row["days"] in ranks for row in cohort.values())
        sample = [row["change"] for row in matched if cohort[row["code"]]["days"] in ranks]
        if size:
            result["groups"].append({"label": label, "count": size, "observed": len(sample),
                                     "median": round(statistics.median(sample), 2) if sample else None})
    ranked = sorted(matched, key=lambda row: row["change"], reverse=True)
    edge = ranked if len(ranked) <= 6 else [*ranked[:3], *ranked[-3:]]
    result["movers"] = [{**row, "previous_days": cohort[row["code"]]["days"]} for row in edge]
    return result


@router.get("/market-follow-through")
async def market_follow_through(session: date, previous_session: date):
    now = datetime.now(SHANGHAI)
    if not MIN_DATE <= previous_session < session <= completed_cutoff(now.date(), now) or (session - previous_session).days > 21:
        raise HTTPException(422, "请选择相邻且已收盘的交易日")
    try:
        calendar_bars, calendar_url = await tencent_candles("510300.SH", previous_session, session)
    except (ValueError, TypeError, OSError, KeyError, IndexError, TimeoutError):
        raise HTTPException(503, "参考日线暂不可用，无法核对相邻交易日")
    days = [bar["date"] for bar in calendar_bars if bar["volume"] > 0]
    if days != [previous_session.isoformat(), session.isoformat()]:
        raise HTTPException(422, "沪深参考 ETF 未能确认这两个日期是相邻交易日")
    prior, observed, current = await asyncio.gather(
        read_pool("up", previous_session), read_pool("previous", session), read_pool("up", session),
    )
    return {
        "session": session, "previous_session": previous_session,
        **follow_through_summary(prior, observed, current),
        "sources": [
            {"label": "沪深参考 ETF 日线", "url": calendar_url},
            {"label": "上一交易日涨停池", "url": prior["source"], "verified": prior["count"] is not None},
            {"label": "昨涨停股次日行情", "url": observed["source"], "verified": observed["count"] is not None},
            {"label": "当日涨停池", "url": current["source"], "verified": current["count"] is not None},
        ],
    }
