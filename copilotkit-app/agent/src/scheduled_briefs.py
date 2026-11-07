"""Evidence-based scheduled briefs with explicit universe and time windows."""
import asyncio
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .market_review import SHANGHAI, completed_cutoff
from .research_data import cash_hours, candles, cli, close_buffer_minutes, exchange_calendar, exchange_sessions, market_zone, tencent_candles
from .research_models import ResearchConfig, normalize_symbol
from .research_store import save_report

Workflow = Literal["stock", "morning", "news", "watch", "filings", "weekly"]
NAMES = {"morning": "市场晨报", "news": "要闻综述", "watch": "自选股异动", "filings": "公告追踪", "weekly": "每周自选复盘"}
BASKETS = {
    "HK": ["2800.HK", "2828.HK", "3033.HK"],
    "US": ["SPY.US", "QQQ.US", "DIA.US"],
    "SH": ["510300.SH", "510050.SH", "510500.SH"],
    "SZ": ["159915.SZ", "159919.SZ", "159949.SZ"],
    "SG": ["ES3.SG", "D05.SG", "O39.SG"],
}
TOPICS = {"HK": "港股", "US": "美股", "SH": "A股", "SZ": "A股", "SG": "新加坡股市"}
PRICE_WORKFLOWS = {"morning", "watch", "weekly"}
BRIEF_LOOKBACK = 28
DATA_FAILURES = (RuntimeError, ValueError, TypeError, AttributeError, KeyError, IndexError, OSError, TimeoutError)


class BriefOptions(BaseModel):
    workflow: Workflow = "stock"
    symbols: list[str] = Field(default_factory=list, max_length=8)
    keyword: str = Field(default="", max_length=80)
    window_hours: int = Field(default=24, ge=1, le=168)
    move_threshold: float = Field(default=3, gt=0, le=30)

    @field_validator("keyword")
    @classmethod
    def validate_keyword(cls, value):
        value = value.strip()
        if value.startswith("-") or any(ord(char) < 32 for char in value):
            raise ValueError("关键词不能以连字符开头或包含控制字符")
        return value

    def universe(self, config: ResearchConfig):
        fallback = BASKETS[config.market] if self.workflow == "morning" else []
        return list(dict.fromkeys(normalize_symbol(symbol, config.market) for symbol in (self.symbols or fallback)))


def publication_time(row):
    value = next((row.get(key) for key in ("published_at", "publish_at", "time", "timestamp", "date") if row.get(key)), None)
    try:
        if isinstance(value, (int, float)) or isinstance(value, str) and value.isdigit():
            seconds = float(value)
            return datetime.fromtimestamp(seconds / 1000 if seconds > 1e12 else seconds, timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def rows(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("list", "news", "items", "articles", "candlesticks", "data"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ValueError("数据格式无法识别")


async def mainland_sessions(cutoff, count):
    start = cutoff - timedelta(days=BRIEF_LOOKBACK)
    try:
        sessions = await exchange_sessions("SH", start, cutoff)
        if len(sessions) >= count:
            return [str(day) for day in sessions[-count:]], "Longbridge", "https://open.longbridge.com/docs/market/trade-days"
    except DATA_FAILURES:
        pass
    try:
        bars, url = await tencent_candles("510300.SH", start, cutoff)
        sessions = [bar["date"] for bar in bars if bar["volume"] > 0]
        if len(sessions) >= count:
            return sessions[-count:], "腾讯财经", url
    except DATA_FAILURES:
        pass
    raise ValueError("沪深交易日历和参考 ETF 日线均未能确认本期交易日期")


async def completed_market_sessions(market, as_of, now, count):
    zone = market_zone(market)
    end = min(as_of, now.astimezone(zone).date())
    calendar = await exchange_calendar(market, end - timedelta(days=BRIEF_LOOKBACK), end)
    completed = []
    for day, half_day in calendar.items():
        _, closing = cash_hours(market, half_day)
        ready = datetime.combine(day, closing, tzinfo=zone) + timedelta(minutes=close_buffer_minutes(market))
        if ready <= now:
            completed.append(str(day))
    if len(completed) < count:
        raise ValueError("交易日历未确认足够的已收盘交易日")
    return completed[-count:], "Longbridge", "https://open.longbridge.com/docs/market/trade-days"


async def execute_brief(config: ResearchConfig, options: BriefOptions, report_id: str):
    now = datetime.now(timezone.utc)
    started = time.monotonic()
    name = NAMES[options.workflow]
    sources, gaps, points = [], [], []
    report = {
        "id": report_id, "symbol": f"{config.market} {name}", "workflow": options.workflow, "as_of": str(config.as_of),
        "created_at": now.isoformat(), "config": config.model_dump(mode="json"), "status": "running",
        "stages": [{"id": "data", "status": "running"}, {"id": "synthesis", "status": "pending"}],
        "findings": {}, "assessment": None, "elapsed_seconds": 0,
        "evidence": {"sources": sources, "gaps": gaps, "bars": [], "metrics": {},
                     "methodology": ("采用未复权收盘价，按同一组已完成交易日对齐。沪深 15:15 后纳入当日收盘，港美新按市场时区、半日市及收市数据等待时间核对。"
                                     if options.workflow in PRICE_WORKFLOWS else "新闻与公告按真实发布时间筛选。")},
    }
    save_report(report)
    from .infrastructure.telemetry import trace_details
    if trace_details():
        report["observability"] = trace_details()
    semaphore = asyncio.Semaphore(3)

    async def fetch(label, args, calendar):
        if args[0] == "kline":
            try:
                sessions, _, _ = await calendar
                async with semaphore:
                    data = await candles(label, config.model_copy(update={"as_of": date.fromisoformat(sessions[-1])}),
                                         lookback_days=BRIEF_LOOKBACK, required_sessions=sessions)
                return data
            except DATA_FAILURES as exc:
                gaps.append(f"{label}：{exc if isinstance(exc, ValueError) else '收盘日线查询失败'}")
                return None
        async with semaphore:
            try:
                return rows(await cli(*args, fresh=True))
            except Exception as exc:
                gaps.append(f"{label}：{exc if isinstance(exc, (RuntimeError, ValueError)) else '数据查询失败'}")
                return None

    def source(kind, title, content, published_at, url, provider="Longbridge"):
        key = f"S{len(sources) + 1}"
        sources.append({"id": key, "kind": kind, "title": title, "content": content, "published_at": published_at,
                        "url": url, "provider": provider, "excerpt_only": kind not in {"prices", "calendar"}})
        return key

    symbols = options.universe(config)
    queries = []
    if options.workflow in PRICE_WORKFLOWS:
        queries.extend((symbol, ("kline", symbol, "--count", "16", "--adjust", "none")) for symbol in symbols)
    if options.workflow in ("morning", "news"):
        queries.append(("要闻", ("news", "search", options.keyword or TOPICS[config.market], "--count", "30")))
    if options.workflow == "filings":
        queries.extend((symbol, ("filing", symbol, "--count", "30")) for symbol in symbols)

    try:
        span = 5 if options.workflow == "weekly" else 1
        local_now = now.astimezone(SHANGHAI)
        cutoff = completed_cutoff(min(config.as_of, local_now.date()), local_now)
        calendar = None
        if options.workflow in PRICE_WORKFLOWS:
            calendar = asyncio.create_task(mainland_sessions(cutoff, span + 1) if config.market in {"SH", "SZ"}
                                           else completed_market_sessions(config.market, config.as_of, now, span + 1))
        results = await asyncio.gather(*(fetch(label, args, calendar) for label, args in queries))
        seen, headlines = set(), []
        priced = 0
        calendar_id = None
        for (label, args), data in zip(queries, results):
            if data is None:
                continue
            if args[0] == "kline":
                sessions, calendar_provider, calendar_url = calendar.result()
                closes = {bar["date"]: bar["close"] for bar in data["bars"] if bar["volume"] > 0}
                if any(day not in closes for day in sessions):
                    missing = "、".join(day for day in sessions if day not in closes)
                    gaps.append(f"{label}：缺少 {missing} 的有效成交日线，未计算本期涨跌。")
                    continue
                first, last = sessions[0], sessions[-1]
                close, change = closes[last], (closes[last] / closes[first] - 1) * 100
                provider, url = data["provider"], data["source"]
                if calendar_id is None:
                    title = f"{config.market} 交易日历" if calendar_provider == "Longbridge" else "沪深参考 ETF 有成交日线"
                    calendar_id = source("calendar", title, "、".join(sessions), last, calendar_url, calendar_provider)
                dates = "\n用于计算的收盘价：" + "；".join(f"{day} {closes[day]:g}" for day in sessions)
                body = f"{label} {first} 至 {last} 收盘 {close:g}，{span} 个交易日涨跌 {change:+.2f}%"
                sid = source("prices", f"{label} 收盘表现", body + dates, str(last), url, provider)
                priced += 1
                if options.workflow != "watch" or abs(change) >= options.move_threshold:
                    points.append(f"{body} [{sid}]" + (f" · {provider}备用行情" if provider != "Longbridge" else ""))
                continue
            cutoff = now - timedelta(hours=options.window_hours)
            timestamps = 0
            for item in data:
                if not isinstance(item, dict):
                    continue
                published = publication_time(item)
                timestamps += bool(published)
                title = str(item.get("file_name") or item.get("title") or "").strip()
                if published and cutoff <= published <= now and title:
                    headlines.append((published, label, item, title, args[0]))
            if data and not timestamps:
                gaps.append(f"{label}：缺少可核验的发布时间，未纳入本期简报")
        for published, label, item, title, kind in sorted(headlines, key=lambda entry: entry[0], reverse=True):
            fingerprint = re.sub(r"[\W_]+", "", title.casefold())
            if fingerprint in seen or len(seen) >= 15:
                continue
            seen.add(fingerprint)
            body = str(item.get("description") or item.get("excerpt") or title)[:1000]
            urls = item.get("file_urls") or []
            url = item.get("url") or (urls[0] if isinstance(urls, list) and urls else "")
            sid = source(kind, title, body, published.isoformat(), url or "https://longbridge.com/")
            points.append(f"{title} [{sid}]" + (f" — {body[:180]}" if body != title else ""))
        if options.workflow == "news":
            summary = f"过去 {options.window_hours} 小时，关键词「{options.keyword or TOPICS[config.market]}」匹配 {len(seen)} 条去重新闻。"
        elif options.workflow == "morning":
            summary = f"观察 {len(symbols)} 个市场代表标的，{priced} 个取得可计算日线，收录过去 {options.window_hours} 小时的 {len(seen)} 条去重新闻。"
        elif options.workflow == "filings":
            summary = f"追踪 {len(symbols)} 家公司，收录过去 {options.window_hours} 小时内发布的 {len(seen)} 条去重公告。"
        elif options.workflow == "watch":
            summary = f"扫描 {len(symbols)} 个自选标的，已取得 {priced} 个标的的完整日线；{len(points)} 个达到 ±{options.move_threshold:g}% 阈值。"
        else:
            summary = f"比较 {len(symbols)} 个自选标的近五个完整交易日的收盘表现，{len(points)} 个标的取得可计算数据。"
        if not points and options.workflow != "watch":
            summary += " 当前返回范围内无符合条件的记录。"
        if gaps:
            summary += f" 有 {len(gaps)} 项数据缺口。"
        report["assessment"] = {
            "summary": summary, "stance": "观察摘要", "key_points": points, "risks": gaps,
            "catalysts": [], "risk_level": "无法判断", "valuation_scenarios": [], "invalidation_conditions": [],
        }
        report["status"] = "failed" if not sources and gaps else "partial" if gaps else "complete"
        report["stages"][0]["status"] = "failed" if report["status"] == "failed" else "complete"
        report["stages"][1]["status"] = "complete"
    except asyncio.CancelledError:
        report["status"] = "cancelled"
        raise
    except Exception:
        report["status"] = "failed"
        raise
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        save_report(report)
    return report
