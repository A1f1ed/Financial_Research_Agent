"""Date-bounded A-share exchange events from Eastmoney public data."""
import asyncio
import json
import math
import re
import time
from decimal import Decimal
from datetime import date, datetime, timedelta
from io import BytesIO
from unicodedata import normalize
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pypdf import PdfReader

from .preferences import read_setting
from .research_store import connect

DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"
PAGE_SIZE = 30
SHANGHAI = ZoneInfo("Asia/Shanghai")
EVENT_NAMES = {"billboard": "龙虎榜", "unlock": "限售解禁", "holder_change": "股东增减持"}
router = APIRouter(prefix="/research")
_provider_lock = asyncio.Lock()
_last_request = 0.0
_filing_slots = asyncio.Semaphore(3)
EXCHANGE_PDF_HOSTS = {"disc.static.szse.cn", "static.cninfo.com.cn", "www.sse.com.cn", "static.sse.com.cn"}


def covered_symbol(symbol: str) -> bool:
    return re.fullmatch(r"(?:60[0135]|68[89])[0-9]{3}\.SH|(?:00[0123]|30[01])[0-9]{3}\.SZ", symbol) is not None


def day(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return value
    return None


async def eastmoney_json(url):
    global _last_request
    def get():
        request = Request(url, headers={"Referer": "https://data.eastmoney.com/"})
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read(1_048_576))

    await asyncio.sleep(max(0, 1.2 - (time.monotonic() - _last_request)))
    try:
        return await asyncio.to_thread(get)
    finally:
        _last_request = time.monotonic()


async def fetch_eastmoney(url, parse, *, cache_key=None):
    cache_key = cache_key or url
    async with asyncio.timeout(20):
        async with _provider_lock:
            with connect() as db:
                cached = db.execute("SELECT body,fetched FROM cache WHERE key=?", (cache_key,)).fetchone()
            ttl = read_setting("data", {"cache_minutes": 15})["cache_minutes"] * 60
            if cached and time.time() - cached[1] < ttl:
                return json.loads(cached[0])
            data = parse(await eastmoney_json(url))
            with connect() as db:
                db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (cache_key, json.dumps(data), time.time()))
            return data


async def fetch_page(kind, symbol, cutoff):
    code = symbol.split(".")[0]
    if kind == "billboard":
        report, field, first, last = "RPT_DAILYBILLBOARD_DETAILSNEW", "TRADE_DATE", cutoff - timedelta(days=30), cutoff
    elif kind == "holder_change":
        report, field, first, last = "RPT_SHARE_HOLDER_INCREASE", "NOTICE_DATE", cutoff - timedelta(days=365), cutoff
    else:
        report, field, first, last = "RPT_LIFT_STAGE", "FREE_DATE", cutoff - timedelta(days=365), cutoff + timedelta(days=90)
    query = {
        "reportName": report, "columns": "ALL", "filter": f'(SECURITY_CODE="{code}")({field}>=\'{first}\')({field}<=\'{last}\')',
        "pageNumber": 1, "pageSize": PAGE_SIZE, "sortColumns": field, "sortTypes": "-1", "source": "WEB", "client": "WEB",
    }
    url = f"{DATACENTER}?{urlencode(query)}"

    def parse(payload):
        if not isinstance(payload, dict):
            raise ValueError("东方财富事件响应格式异常")
        result = payload.get("result")
        # The provider sends this explicit response for a valid empty query.
        if payload.get("code") == 9201 and result is None:
            return []
        if payload.get("success") is True and isinstance(result, dict) and isinstance(result.get("data"), list):
            return result["data"]
        raise ValueError("东方财富事件数据暂不可用")

    return await fetch_eastmoney(url, parse), url


def matching_filing(filings, event_date, cutoff):
    labels = (event_date.isoformat(), f"{event_date.year}年{event_date.month}月{event_date.day}日",
              f"{event_date.year}年{event_date.month:02d}月{event_date.day:02d}日")
    for row in filings if isinstance(filings, (list, tuple)) else ():
        if not isinstance(row, dict):
            continue
        title = str(row.get("file_name") or row.get("title") or "")
        published = filing_day(row)
        if not published or published > cutoff or not ("解除限售" in title or "上市流通" in title):
            continue
        excerpt = str(row.get("description") or row.get("excerpt") or "")
        urls = row.get("file_urls")
        url = row.get("url") or (urls[0] if isinstance(urls, list) and urls else "")
        if any(label in title + excerpt for label in labels) and isinstance(url, str) and url.startswith("https://"):
            return published, title, url
    return None


def filing_day(row):
    stamp = row.get("published_at") or row.get("publish_at") or row.get("time")
    if not isinstance(stamp, str):
        return None
    try:
        timestamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return timestamp.astimezone(SHANGHAI).date() if timestamp.tzinfo else day(stamp) if len(stamp) == 10 else None
    except ValueError:
        return None


def exchange_pdf(url):
    if not isinstance(url, str) or len(url) > 600:
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme == "https" and parsed.netloc in EXCHANGE_PDF_HOSTS and parsed.path.lower().endswith(".pdf"):
        return parsed.path
    return None


class NoFilingRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


async def filing_text(url):
    key = f"issuer-filing-text:v1:{url}"
    with connect() as db:
        cached = db.execute("SELECT body,fetched FROM cache WHERE key=?", (key,)).fetchone()
    if cached and time.time() - cached[1] < 86400:
        return json.loads(cached[0])

    def read():
        limit = 2_000_000
        with build_opener(NoFilingRedirect()).open(Request(url), timeout=4) as response:
            data = response.read(limit + 1)
        if len(data) > limit or not data.startswith(b"%PDF-"):
            return ""
        pdf = PdfReader(BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in pdf.pages[:3])[:24000]

    try:
        async with asyncio.timeout(6):
            async with _filing_slots:
                body = await asyncio.to_thread(read)
    except Exception:
        return ""
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (key, json.dumps(body), time.time()))
    return body


def holder_filing_matches(text, code, event):
    text = re.sub(r"\s+", "", normalize("NFKC", text)).replace(",", "")
    holder = re.sub(r"\s+", "", normalize("NFKC", event["holder"]))
    if not re.search(rf"(?:证券|股票)代码[:：]?{code}(?!\d)", text) or holder not in text:
        return False
    alias = re.search(rf'{re.escape(holder)}\(以下简称[“"「]([^”"」]{{2,24}})[”"」]', text)
    names = (holder, alias[1]) if alias else (holder,)
    start, end = date.fromisoformat(event["start_date"]), date.fromisoformat(event["date"])
    shares = Decimal(str(event["shares_10k"])) * 10000

    def date_matches(value, text, optional_year=False):
        years = re.findall(rf"(?<![\d年])(?:(\d{{4}})年)?0?{value.month}月0?{value.day}日", text)
        return any(year == str(value.year) or (optional_year and not year) for year in years)

    for amount in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)(万股|股)", text):
        if Decimal(amount[1]) * (10000 if amount[2] == "万股" else 1) != shares:
            continue
        context = text[max(0, amount.start() - 200):amount.start()]
        directions = re.findall(r"增持|减持", context[-36:])
        if (directions and directions[-1] == event["state"] and any(name in context for name in names)
                and date_matches(start, context) and date_matches(end, context, start.year == end.year)):
            return True
    return False


async def attach_holder_filings(result, symbol, cutoff, filings):
    holders = sorted((event for event in result["events"] if event["kind"] == "holder_change"),
                     key=lambda event: event["published_at"], reverse=True)
    if not holders or not isinstance(filings, (list, tuple)):
        return result
    candidates = {}
    for event in holders:
        notice = date.fromisoformat(event["published_at"])
        earliest = max(date.fromisoformat(event["date"]), notice - timedelta(days=1))
        for row in filings:
            if not isinstance(row, dict):
                continue
            title = str(row.get("file_name") or row.get("title") or "")
            published = filing_day(row)
            if not published or not earliest <= published <= min(cutoff, notice):
                continue
            if "预披露" in title or not re.search(r"权益变动|增持|减持", title):
                continue
            files = row.get("file_urls")
            for url in files if isinstance(files, list) else [row.get("url")]:
                path = exchange_pdf(url)
                if not path:
                    continue
                dated_path = re.search(r"/(\d{4}-\d{2}-\d{2})/", path)
                if dated_path and dated_path[1] != str(notice) or (published != notice and not dated_path):
                    continue
                if url in candidates or len(candidates) < 6:
                    candidates.setdefault(url, []).append((event, title))
    if not candidates:
        return result
    texts = await asyncio.gather(*(filing_text(url) for url in candidates))
    for (url, matches), body in zip(candidates.items(), texts):
        for event, title in matches:
            if not event["filing_url"] and holder_filing_matches(body, symbol.split(".")[0], event):
                event["filing_url"] = url
                event["note"] += f" 公告原文已核对：{title[:120]}。"
    return result


def holder_change(row, symbol, cutoff):
    # This dataset returns the six-digit code rather than SECUCODE.
    if not covered_symbol(symbol) or row.get("SECURITY_CODE") != symbol.split(".")[0]:
        return None
    notice = day(row.get("NOTICE_DATE"))
    start, end = day(row.get("START_DATE")), day(row.get("END_DATE"))
    if not notice or not start or not end or not start <= end <= notice <= cutoff or notice < cutoff - timedelta(days=365):
        return None
    ingested = row.get("EITIME")
    if ingested and (day(ingested) is None or day(ingested) > cutoff):
        return None
    holder, direction = row.get("HOLDER_NAME"), row.get("DIRECTION")
    if not isinstance(holder, str) or not holder.strip() or direction not in ("增持", "减持"):
        return None
    shares = number(row.get("CHANGE_NUM_SYMBOL"))
    if shares is None or shares == 0 or (shares > 0) != (direction == "增持"):
        return None
    channel = str(row.get("MARKET") or "").strip()[:35]
    description = f"{holder.strip()[:160]}披露{direction} {abs(shares):,.4f} 万股。变动区间 {start} 至 {end}。"
    hold_ratio = number(row.get("HOLD_RATIO"))
    if hold_ratio is not None and 0 <= hold_ratio <= 100:
        description += f"变动后持股占总股本 {hold_ratio:g}%。"
    if channel:
        description += f"变动方式：{channel}。"
    return {"date": str(end), "published_at": str(notice), "state": direction, "description": description,
            "holder": holder.strip(), "start_date": str(start), "shares_10k": abs(shares),
            "note": f"公告日 {notice}。本证据为抽取的披露样本，变动区间可能重叠。", "filing_url": None}


def normalize_events(pages, symbol, cutoff, filings=()):
    events, gaps = [], []
    now = datetime.now(SHANGHAI)
    for kind, page in zip(EVENT_NAMES, pages):
        name = EVENT_NAMES[kind]
        if isinstance(page, BaseException):
            gaps.append(f"{name}：数据源暂不可用")
            continue
        rows, url = page
        accepted = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if kind == "holder_change":
                event = holder_change(row, symbol, cutoff)
                if event:
                    accepted.append({**event, "kind": kind, "title": name, "url": url, "provider": "东方财富"})
                continue
            if row.get("SECUCODE") != symbol:
                continue
            event_date = day(row.get("TRADE_DATE" if kind == "billboard" else "FREE_DATE"))
            if not event_date:
                continue
            if kind == "billboard":
                if not cutoff - timedelta(days=30) <= event_date <= cutoff or (event_date == now.date() and now.hour < 20):
                    continue
                reason = str(row.get("EXPLANATION") or "上榜原因未提供")[:220]
                amount = number(row.get("BILLBOARD_NET_AMT"))
                description = reason + (f"。该上榜口径净额 {amount / 10000:,.2f} 万元。" if amount is not None else "。该上榜口径净额未提供。")
                published, proof, state = None, None, "已发生"
                note = "日期为交易日。上榜净额只对应此披露口径，同日多条不能直接相加。"
            else:
                if not cutoff - timedelta(days=365) <= event_date <= cutoff + timedelta(days=90):
                    continue
                updated = day(row.get("EUTIME"))
                proof = matching_filing(filings, event_date, cutoff)
                if not updated or updated > cutoff or (event_date > cutoff and not proof):
                    continue
                description = str(row.get("FREE_SHARES_TYPE") or "限售股份")[:120]
                shares = number(row.get("ABLE_FREE_SHARES"))
                if shares is not None and shares >= 0:
                    description += f"。数据源列示可流通 {shares:,.4f} 万股。"
                published = proof[0] if proof else None
                state = "已披露待发生" if event_date > cutoff else "历史解禁"
                note = f"东财记录时间 {updated}。解禁仅表示流通资格。"
                if proof:
                    note += f"公告佐证：{proof[1]}"
            accepted.append({"kind": kind, "title": name, "date": str(event_date),
                             "published_at": str(published) if published else None, "state": state,
                             "description": description, "note": note, "url": url, "provider": "东方财富",
                             "filing_url": proof[2] if proof else None})
        if not accepted:
            gaps.append(f"{name}：在查询区间内未取得符合截止日和披露校验的记录")
        elif len(accepted) < len(rows):
            gaps.append(f"{name}：已排除日期、证券或披露证据不符的记录")
        if len(accepted) > 8:
            gaps.append(f"{name}：最多显示 8 条最近的合格记录")
        elif kind == "holder_change" and len(rows) >= PAGE_SIZE:
            gaps.append(f"{name}：仅核对公告日期最新的 {PAGE_SIZE} 条来源记录")
        events.extend(accepted[:8])
    return {"events": sorted(events, key=lambda item: item["date"], reverse=True), "gaps": gaps}


async def fetch_event_pages(symbol, cutoff):
    return await asyncio.gather(*(fetch_page(kind, symbol, cutoff) for kind in EVENT_NAMES), return_exceptions=True)


@router.get("/a-share-events")
async def preview_events(symbol: str, as_of: date):
    from .research_data import cli

    symbol = symbol.strip().upper()
    if not covered_symbol(symbol):
        raise HTTPException(422, "该入口适用于沪深 A 股代码")
    if not date(2000, 1, 1) <= as_of <= datetime.now(SHANGHAI).date():
        raise HTTPException(422, "请选择有效的信息截止日期")
    async def filings():
        try:
            payload = await asyncio.wait_for(cli("filing", symbol, "--count", "100"), timeout=7)
            return payload if isinstance(payload, list) else payload.get("list", [])
        except (RuntimeError, ValueError, TimeoutError, OSError, AttributeError):
            return []

    pages, company_filings = await asyncio.gather(fetch_event_pages(symbol, as_of), filings())
    return await attach_holder_filings(normalize_events(pages, symbol, as_of, company_filings), symbol, as_of, company_filings)
