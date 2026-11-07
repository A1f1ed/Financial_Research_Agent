"""Read-only Longbridge adapter, publication cutoffs and reproducible indicators."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import shutil
import statistics
import subprocess
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .research_models import ResearchConfig, normalize_symbol
from .persistence.business import BusinessRepository
from .preferences import read_setting
from .a_share_events import attach_holder_filings, covered_symbol, fetch_event_pages, normalize_events

ALLOWED_COMMANDS = {"kline", "news", "topic", "filing", "financial-report", "trading"}
CALENDAR_MARKETS = {"CN", "HK", "US", "SG"}


def cli_path():
    configured = os.getenv("LONGBRIDGE_CLI_PATH")
    candidates = [configured, shutil.which("longbridge"),
                  str(Path(os.getenv("LOCALAPPDATA", "")) / "Programs/longbridge/longbridge.exe")]
    return next((p for p in candidates if p and Path(p).is_file()), None)


async def cli(*args, fresh=False):
    if not args or args[0] not in ALLOWED_COMMANDS:
        raise ValueError("Only approved read-only market-data commands are allowed")
    if args[0] == "trading" and (len(args) < 3 or args[1] != "days" or args[2] not in CALENDAR_MARKETS):
        raise ValueError("Only approved read-only market-data commands are allowed")
    binary = cli_path()
    if not binary:
        raise RuntimeError("未找到 Longbridge CLI；设置 LONGBRIDGE_CLI_PATH 并在本机完成 longbridge auth login")
    key = json.dumps(args)
    cache_seconds = read_setting("data", {"cache_minutes": 15})["cache_minutes"] * 60
    cached = BusinessRepository().cached(key, cache_seconds) if not fresh else None
    if cached is not None:
        return cached
    # Popen's blocking pipe collection runs in a thread, retaining explicit
    # cancellation/timeout cleanup while allowing psycopg's Selector loop on Windows.
    process = subprocess.Popen([binary, *args, "--format", "json", "--lang", "zh-CN"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        **({"creationflags": 0x08000000} if os.name == "nt" else {}))
    communication = asyncio.create_task(asyncio.to_thread(process.communicate))
    try:
        stdout, stderr = await asyncio.wait_for(asyncio.shield(communication), timeout=35)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        if process.poll() is None:
            process.kill()
        await communication
        raise
    if process.returncode:
        # Provider errors are safe summaries; don't return arbitrary stderr/token paths.
        message = stderr.decode("utf-8", errors="replace")
        if "301607" in message or "permission" in message.lower():
            raise RuntimeError("数据源权限不足：当前账户未开通此历史行情权限")
        if "auth" in message.lower() or "token" in message.lower():
            raise RuntimeError("Longbridge 授权失效，请在本机运行 longbridge auth login")
        raise RuntimeError(f"Longbridge {args[0]} 查询失败（退出码 {process.returncode}）")
    result = json.loads(stdout)
    BusinessRepository().put_cache(key, result)
    return result


async def exchange_calendar(market, start, end):
    exchange = "CN" if market in {"SH", "SZ"} else market
    payload = await asyncio.wait_for(cli("trading", "days", exchange, "--start", str(start), "--end", str(end)), timeout=6)
    if not isinstance(payload, dict) or any(not isinstance(payload.get(key), list) for key in ("trading_days", "half_trading_days")):
        raise ValueError("交易日历格式无法识别")
    half_days = {date.fromisoformat(day) for day in payload["half_trading_days"]}
    sessions = sorted({date.fromisoformat(day) for day in payload["trading_days"]} | half_days)
    if sessions and not start <= sessions[0] <= sessions[-1] <= end:
        raise ValueError("交易日历日期超出查询范围")
    return {day: day in half_days for day in sessions}


async def exchange_sessions(market, start, end):
    return list(await exchange_calendar(market, start, end))


def market_zone(market):
    return ZoneInfo("America/New_York" if market == "US" else "Asia/Hong_Kong")


def cash_hours(market, half_day=False):
    # Cash-equity anchors, excluding pre/post-market and closing routines. Callers add a publication buffer.
    closing_hours = {"SH": 15, "SZ": 15, "CN": 15, "HK": 16, "US": 16, "SG": 17}
    if half_day and market in {"SH", "SZ", "CN"}:
        raise ValueError("沪深半日市收盘时点尚未确认")
    opening = dt_time(9, 0) if market == "SG" else dt_time(9, 30)
    closing = dt_time((13 if market == "US" else 12) if half_day else closing_hours[market], 0)
    return opening, closing


def close_buffer_minutes(market):
    return 20 if market == "SG" else 15


def local_date(value, market="HK"):
    if value is None or value == "":
        return None
    tz = ZoneInfo("America/New_York" if market == "US" else "Asia/Hong_Kong")
    try:
        text = str(value)
        if text.replace(".", "", 1).isdigit():
            seconds = float(text)
            if seconds > 1e12:
                seconds /= 1000
            return datetime.fromtimestamp(seconds, timezone.utc).astimezone(tz).date()
        if len(text) == 10:
            return date.fromisoformat(text)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        # Missing timezone is not silently assumed to be a trustworthy timestamp.
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(tz).date()
    except (ValueError, TypeError, OverflowError):
        return None


def eligible(record, cutoff, market="HK"):
    published = next((record.get(k) for k in ("published_at", "publish_at", "time", "timestamp", "date") if record.get(k)), None)
    day = local_date(published, market)
    return day is not None and day <= cutoff


def longbridge_bars(rows, start, cutoff, market):
    result = []
    for row in rows if isinstance(rows, list) else rows.get("candlesticks", []):
        if not isinstance(row, dict):
            continue
        day = local_date(row.get("time") or row.get("timestamp"), market)
        if day is None or not start <= day <= cutoff:
            continue
        try:
            values = {key: float(row[key]) for key in ("open", "high", "low", "close", "volume")}
            if not all(math.isfinite(v) for v in values.values()) or values["close"] <= 0:
                continue
            result.append({"date": day.isoformat(), **values})
        except (KeyError, ValueError, TypeError):
            continue
    return sorted({row["date"]: row for row in result}.values(), key=lambda row: row["date"])


TENCENT_KLINE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def tencent_bars(payload, symbol, start, cutoff):
    code, market = symbol.split(".")
    rows = payload["data"][market.lower() + code]["day"]
    if payload["code"] != 0 or not isinstance(rows, list) or len(rows) > 640:
        raise ValueError("腾讯日线响应异常")
    volume_scale = 1 if market == "SH" and code.startswith(("688", "689")) else 100
    result = {}
    for row in rows:
        day, *raw = row[:6]
        if not start <= date.fromisoformat(day) <= cutoff or day in result:
            raise ValueError("腾讯日线日期越界或重复")
        if any(isinstance(value, bool) for value in raw):
            raise ValueError("腾讯日线数值异常")
        opening, close, high, low, volume = map(float, raw)
        if not all(math.isfinite(v) for v in (opening, close, high, low, volume)) or not 0 < low <= min(opening, close) <= max(opening, close) <= high or volume < 0:
            raise ValueError("腾讯日线数值异常")
        result[day] = {"date": day, "open": opening, "high": high, "low": low, "close": close, "volume": volume * volume_scale}
    return [result[day] for day in sorted(result)]


async def tencent_candles(symbol, start, cutoff):
    code, market = symbol.split(".")
    url = TENCENT_KLINE + "?" + urlencode({"param": f"{market.lower()}{code},day,{start},{cutoff},640,"})
    key = json.dumps(["tencent-unadjusted-daily", symbol, str(start), str(cutoff)])
    cached = BusinessRepository().cached(key, read_setting("data", {"cache_minutes": 15})["cache_minutes"] * 60)
    if cached is not None:
        return cached, url

    def fetch():
        request = Request(url, headers={"Referer": "https://gu.qq.com/"})
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read(512_000))

    payload = await asyncio.wait_for(asyncio.to_thread(fetch), timeout=6)
    bars = tencent_bars(payload, symbol, start, cutoff)
    if bars:
        BusinessRepository().put_cache(key, bars)
    return bars, url


async def candles(symbol, config, *, lookback_days=420, required_sessions=()):
    symbol = normalize_symbol(symbol)
    code, market = symbol.split(".")
    cutoff = config.as_of
    start = cutoff - timedelta(days=lookback_days)
    mainland = market in {"SH", "SZ"} and len(code) == 6 and code.isascii() and code.isdigit()
    provider, source = "Longbridge", f"https://longbridge.com/quote/{symbol}"
    bars, notes = [], []

    def complete(series):
        if required_sessions:
            return set(required_sessions).issubset(bar["date"] for bar in series if bar["volume"] > 0)
        return len(series) >= 2

    for args, message in (
        (("history", symbol, "--start", str(start), "--end", str(cutoff), "--adjust", "none"), "Longbridge 历史区间日线未取得足够记录"),
        ((symbol, "--count", "1000", "--adjust", "none"), "Longbridge 最近日线未覆盖足够的指定区间记录"),
    ):
        try:
            rows = await asyncio.wait_for(cli("kline", *args), timeout=6) if mainland else await cli("kline", *args)
            candidate = longbridge_bars(rows, start, cutoff, market)
            if len(candidate) > len(bars) or complete(candidate):
                bars = candidate
            if complete(bars):
                break
        except (RuntimeError, ValueError, TypeError, AttributeError, OSError, TimeoutError):
            pass
        notes.append(message)
    if not complete(bars) and mainland:
        try:
            alternate, alternate_url = await tencent_candles(symbol, start, cutoff)
            if len(alternate) > len(bars) or complete(alternate):
                bars, source, provider = alternate, alternate_url, "腾讯财经"
                notes.append("已回退至腾讯财经未复权日线")
        except (URLError, ValueError, TypeError, KeyError, IndexError, OSError, TimeoutError):
            notes.append("腾讯财经备用日线暂不可用")
    return {"symbol": symbol, "bars": bars[-280:], "note": "；".join(notes) or None,
            "provider": provider, "source": source,
            "adjustment": "none", "warning": "未复权日线：拆股、分红可能造成指标跳变；不视为总回报。"}


def indicators(bars):
    closes = [b["close"] for b in bars]
    if not closes:
        return {}
    out = {"close": closes[-1], "last_session": bars[-1]["date"], "observations": len(closes)}
    for n in (5, 10, 20, 60):
        out[f"ma{n}"] = round(statistics.mean(closes[-n:]), 4) if len(closes) >= n else None
    def ema(values, span):
        current = values[0]
        result = [current]
        for value in values[1:]:
            current += 2 / (span + 1) * (value - current)
            result.append(current)
        return result
    if len(closes) >= 35:
        dif = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26))]
        dea = ema(dif, 9)
        out["macd"] = {"dif": round(dif[-1], 4), "dea": round(dea[-1], 4), "histogram": round(2 * (dif[-1] - dea[-1]), 4)}
    if len(closes) >= 15:
        changes = [b - a for a, b in zip(closes, closes[1:])]
        gain = statistics.mean(max(c, 0) for c in changes[:14])
        loss = statistics.mean(max(-c, 0) for c in changes[:14])
        for c in changes[14:]:
            gain, loss = (gain * 13 + max(c, 0)) / 14, (loss * 13 + max(-c, 0)) / 14
        out["rsi14"] = round(50 if gain == loss == 0 else 100 if loss == 0 else 100 - 100 / (1 + gain / loss), 2)
    if len(closes) >= 20:
        mid, std = statistics.mean(closes[-20:]), statistics.pstdev(closes[-20:])
        out["bollinger"] = {"upper": round(mid + 2 * std, 4), "middle": round(mid, 4), "lower": round(mid - 2 * std, 4)}
    for n in (1, 5, 20, 60, 120):
        out[f"return_{n}d"] = round((closes[-1] / closes[-n - 1] - 1) * 100, 2) if len(closes) > n else None
    peak, drawdown = closes[0], 0
    for value in closes:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    out["max_drawdown_pct"] = round(drawdown * 100, 2)
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    out["annualized_volatility_pct"] = round(statistics.stdev(returns) * math.sqrt(252) * 100, 2) if len(returns) > 1 else None
    return out


def relative_returns(stock, benchmark):
    left, right = {b["date"]: b["close"] for b in stock}, {b["date"]: b["close"] for b in benchmark}
    common = sorted(left.keys() & right.keys())
    out = {"aligned_sessions": len(common), "as_of": common[-1] if common else None}
    for n in (20, 60, 120):
        out[f"excess_{n}d_pct"] = round(((left[common[-1]] / left[common[-n-1]] - 1) -
            (right[common[-1]] / right[common[-n-1]] - 1)) * 100, 2) if len(common) > n else None
    return out


async def collect_evidence(config: ResearchConfig):
    sources, gaps, excluded = [], [], 0
    datasets = {}
    semaphore = asyncio.Semaphore(3)
    async def fetch(name, call):
        async with semaphore:
            try:
                datasets[name] = await call()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                gaps.append(f"{name}: {error if isinstance(error, RuntimeError) else '数据请求失败'}")
    jobs = [("prices", lambda: candles(config.symbol, config))]
    if "index" in config.analysts:
        jobs.append(("benchmark", lambda: candles(config.benchmark, config)))
    if "sector" in config.analysts:
        for peer in config.peers:
            jobs.append((f"peer:{peer}", lambda p=peer: candles(p, config)))
    # News and filings provide timestamped evidence for every research role.
    jobs += [("news", lambda: cli("news", config.symbol, "--count", "80")),
             ("filings", lambda: cli("filing", config.symbol, "--count", "100"))]
    if "sentiment" in config.analysts:
        jobs.append(("sentiment", lambda: cli("topic", config.symbol, "--count", "60")))
    if "fundamentals" in config.analysts:
        jobs.append(("financials", lambda: cli("financial-report", config.symbol, "--kind", "ALL", "--report", "af")))
    if covered_symbol(config.symbol) and ({"news", "fundamentals", "sentiment"} & set(config.analysts) or config.include_risk):
        jobs.insert(1, ("a_share_events", lambda: fetch_event_pages(config.symbol, config.as_of)))
    await asyncio.gather(*(fetch(name, call) for name, call in jobs))
    def add(kind, title, content, published_at, url, provider="Longbridge", **extra):
        sources.append({"id": f"S{len(sources)+1}", "kind": kind, "title": title, "content": content,
                        "published_at": published_at, "url": url, "provider": provider, **extra})
    for name in ("prices", "benchmark", *(f"peer:{p}" for p in config.peers)):
        data = datasets.get(name)
        if not data:
            continue
        if data["note"]:
            gaps.append(f"{data['symbol']}: {data['note']}")
        if data["bars"]:
            add("prices", f"{data['symbol']} 日线及代码计算指标", json.dumps(indicators(data["bars"]), ensure_ascii=False),
                data["bars"][-1]["date"], data["source"], provider=data["provider"], symbol=data["symbol"])
        else:
            gaps.append(f"{data['symbol']}: 数据源返回的日线中没有所选截止日之前的记录")
    raw_filings = datasets.get("filings", [])
    if "a_share_events" in datasets:
        filings = raw_filings if isinstance(raw_filings, list) else raw_filings.get("list", []) if isinstance(raw_filings, dict) else []
        market_events = normalize_events(datasets["a_share_events"], config.symbol, config.as_of, filings)
        await attach_holder_filings(market_events, config.symbol, config.as_of, filings)
        gaps.extend(market_events["gaps"])
        for event in market_events["events"]:
            add(event["kind"], f"{event['date']} {event['title']} · {event['state']}",
                f"{event['description']} {event['note']}", event["published_at"], event["url"],
                provider=event["provider"], event_date=event["date"], filing_url=event["filing_url"])
    for name in ("news", "filings", "sentiment"):
        rows = datasets.get(name, [])
        rows = rows if isinstance(rows, list) else rows.get("list", [])
        accepted = []
        for row in rows:
            if not eligible(row, config.as_of, config.market):
                excluded += 1
                continue
            if len(accepted) < (24 if config.depth == "deep" else 14):
                accepted.append(row)
        for row in accepted:
            title = row.get("file_name") or row.get("title") or "社区讨论"
            body = row.get("description") or row.get("excerpt") or title
            urls = row.get("file_urls", [])
            add(name, title, str(body)[:4000], row.get("published_at") or row.get("publish_at") or row.get("time"),
                row.get("url") or (urls[0] if urls else f"https://longbridge.com/quote/{config.symbol}"),
                provider_id=row.get("id"), excerpt_only=True)
        if not accepted:
            gaps.append(f"{name}: 当前返回窗口内没有带有效发布时间、且早于截止日的记录；不代表历史上没有相关事件")
    # Expand a few timestamp-eligible news articles, never fetch arbitrary user URLs.
    for source in [s for s in sources if s["kind"] == "news"][:4 if config.depth == "deep" else 2]:
        if source.get("provider_id"):
            try:
                detail = await cli("news", "detail", str(source["provider_id"]))
                if detail.get("body"):
                    source["content"] = str(detail["body"])[:10000]
                    source["excerpt_only"] = False
            except (RuntimeError, ValueError):
                pass
    # Financial period end is NOT a publication timestamp. Only include values
    # with an explicit publication field or a matched, dated annual-report filing.
    normalized_financials = []
    financials = datasets.get("financials", {})
    eligible_filings = [f for f in raw_filings if eligible(f, config.as_of, config.market)] if isinstance(raw_filings, list) else []
    for statement, group in financials.get("list", {}).items() if isinstance(financials, dict) else []:
        for indicator in group.get("indicators", []):
            for account in indicator.get("accounts", []):
                accepted_values = []
                for value in account.get("values", [])[:4]:
                    year = str(value.get("year", ""))
                    proof = next((f for f in eligible_filings if year and year in (f.get("file_name", "") + f.get("title", ""))
                        and any(word in (f.get("file_name", "") + f.get("title", "")).lower() for word in ("annual report", "年報", "年度报告", "年度報告"))), None)
                    if proof:
                        accepted_values.append({**{k: value.get(k) for k in ("year", "period", "value", "yoy")},
                                                "publication_date": proof.get("publish_at")})
                if accepted_values:
                    normalized_financials.append({"statement": statement, "name": account.get("name"), "field": account.get("field"),
                        "currency": indicator.get("currency"), "percent": account.get("percent"), "values": accepted_values})
    if normalized_financials:
        add("fundamentals", "具有年报发布时间佐证的财务指标", json.dumps(normalized_financials[:28], ensure_ascii=False),
            max(v["publication_date"] for a in normalized_financials for v in a["values"]), f"https://longbridge.com/quote/{config.symbol}")
    elif "fundamentals" in config.analysts:
        gaps.append("财务接口仅提供报告期末，无法证明当时已公开的数值已排除；基本面分析只引用有日期的新闻/公告，不使用未核实三表数字。")
    prices = datasets.get("prices", {}).get("bars", [])
    benchmark = datasets.get("benchmark", {}).get("bars", [])
    metrics = indicators(prices)
    relative = relative_returns(prices, benchmark)
    if benchmark and prices:
        data = datasets["benchmark"]
        add("index", f"相对 {config.benchmark} 的同期收益（基准为ETF代理）", json.dumps(relative, ensure_ascii=False),
            relative["as_of"], data["source"], provider=" / ".join(dict.fromkeys([datasets["prices"]["provider"], data["provider"]])))
    peers = []
    for peer in config.peers:
        bars = datasets.get(f"peer:{peer}", {}).get("bars", [])
        if bars and prices:
            data = datasets[f"peer:{peer}"]
            comparison = {"symbol": peer, **relative_returns(prices, bars)}
            peers.append(comparison)
            add("sector", f"与用户选择的 {peer} 同期比较（非整个板块）", json.dumps(comparison, ensure_ascii=False),
                comparison["as_of"], data["source"], provider=" / ".join(dict.fromkeys([datasets["prices"]["provider"], data["provider"]])))
    return {"sources": sources, "gaps": gaps, "excluded_after_cutoff_or_undated": excluded,
            "bars": prices, "metrics": metrics, "relative": relative, "peers": peers,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "methodology": "发布时间/交易日按市场时区过滤。滚动接口不是历史全量档案；文档可能经事后修订，非严格历史数据库回放。技术指标基于未复权日线。"}
