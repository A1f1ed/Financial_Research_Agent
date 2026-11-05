"""Compare a declared A-share sample on the same completed trading session."""
import asyncio
import statistics
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from .research_data import candles
from .research_models import ResearchConfig, normalize_symbol

router = APIRouter(prefix="/research")
SHANGHAI = ZoneInfo("Asia/Shanghai")
MIN_DATE = date(2000, 1, 1)


def mainland_symbol(value: str) -> str:
    if "." not in value:
        raise ValueError("请为证券代码加上 .SH 或 .SZ 后缀")
    symbol = normalize_symbol(value)
    code, exchange = symbol.split(".")
    if len(code) != 6 or not code.isascii() or not code.isdigit() or exchange not in {"SH", "SZ"}:
        raise ValueError("请输入带 .SH 或 .SZ 后缀的六位 A 股或 ETF 代码")
    return symbol


class ReviewRequest(BaseModel):
    as_of: date
    benchmark: str
    symbols: list[str] = Field(min_length=1, max_length=8)

    @field_validator("benchmark")
    @classmethod
    def validate_benchmark(cls, value):
        return mainland_symbol(value)

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, values):
        return list(dict.fromkeys(mainland_symbol(value) for value in values))


def completed_cutoff(requested: date, now: datetime) -> date:
    if requested == now.date() and now.time() < time(15, 15):
        return requested - timedelta(days=1)
    return requested


def review_row(symbol, data, session, previous_session):
    bars = data["bars"]
    closes = {bar["date"]: bar for bar in bars}
    latest, previous = closes.get(session), closes.get(previous_session)
    if not latest or not previous or latest["volume"] <= 0 or previous["volume"] <= 0:
        return None
    volumes = [bar["volume"] for bar in bars if bar["date"] < session and bar["volume"] > 0][-20:]
    return {
        "symbol": symbol,
        "close": latest["close"],
        "day_pct": round((latest["close"] / previous["close"] - 1) * 100, 4),
        "volume_ratio": round(latest["volume"] / statistics.mean(volumes), 3) if len(volumes) == 20 else None,
        "source": data["source"],
        "provider": data["provider"],
    }


@router.post("/market-review")
async def market_review(request: ReviewRequest):
    now = datetime.now(SHANGHAI)
    if not MIN_DATE <= request.as_of <= now.date():
        raise HTTPException(422, "复盘日期必须介于 2000-01-01 和北京时间今天之间")
    cutoff = completed_cutoff(request.as_of, now)
    semaphore = asyncio.Semaphore(3)

    async def fetch(symbol):
        async with semaphore:
            try:
                config = ResearchConfig(symbol=symbol, market=symbol.split(".")[1], as_of=cutoff, peers=[])
                return await asyncio.wait_for(candles(symbol, config, lookback_days=75), timeout=20)
            except Exception:
                return {"bars": [], "note": "行情暂不可用，可能超时或缺少数据权限"}

    symbols = list(dict.fromkeys([request.benchmark, *request.symbols]))
    series = dict(zip(symbols, await asyncio.gather(*(fetch(symbol) for symbol in symbols))))
    benchmark_data = series[request.benchmark]
    benchmark_bars = [bar for bar in benchmark_data["bars"] if bar["volume"] > 0]
    if len(benchmark_bars) < 2:
        raise HTTPException(503, "基准缺少两个有成交的日线交易日，请检查数据源或更换基准后重试")
    previous, session = (bar["date"] for bar in benchmark_bars[-2:])
    benchmark = review_row(request.benchmark, benchmark_data, session, previous)
    sample = []
    gaps = []
    for symbol in symbols:
        data = series[symbol]
        bars, note = data["bars"], data["note"]
        if note:
            gaps.append({"symbol": symbol, "reason": note})
        if symbol not in request.symbols:
            continue
        row = review_row(symbol, data, session, previous)
        if row:
            row["relative_pct"] = round(row["day_pct"] - benchmark["day_pct"], 4)
            sample.append(row)
        elif not note or bars:
            gaps.append({"symbol": symbol, "reason": "未同时取得两个基准交易日的有效成交日线"})
    return {
        "requested_date": request.as_of,
        "session": session,
        "previous_session": previous,
        "benchmark": benchmark,
        "requested_count": len(request.symbols),
        "symbols": request.symbols,
        "sample": sorted(sample, key=lambda row: row["day_pct"], reverse=True),
        "gaps": gaps,
    }
