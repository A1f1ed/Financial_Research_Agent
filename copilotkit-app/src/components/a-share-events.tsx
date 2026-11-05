"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, LoaderCircle } from "lucide-react";
import { researchRequest } from "./workbench-panels";

export function canPreviewAEvents(symbol: string, market: string) {
  const normalized = symbol.trim().toUpperCase();
  const qualified = normalized.includes(".") ? normalized : `${normalized}.${market}`;
  const valid = /^(?:(?:60[0135]|68[89])[0-9]{3}\.SH|(?:00[0123]|30[01])[0-9]{3}\.SZ)$/.test(qualified);
  return valid && qualified.endsWith(`.${market}`) ? qualified : null;
}

type Event = {
  kind: string; title: string; date: string; state: string; description: string; note: string;
  url: string; filing_url: string | null; published_at: string | null; provider: string;
};
const eventFilters = { all: "全部", billboard: "龙虎榜", unlock: "限售解禁", holder_change: "股东增减持" } as const;

export function AShareEvents({ symbol, asOf }: { symbol: string; asOf: string }) {
  const [result, setResult] = useState<{ events: Event[]; gaps: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<keyof typeof eventFilters>("all");
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);

  async function preview() {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError("");
    try {
      const params = new URLSearchParams({ symbol, as_of: asOf });
      const data = await researchRequest<{ events: Event[]; gaps: string[] }>(`a-share-events?${params}`, "GET", undefined, controller.signal);
      if (!controller.signal.aborted) setResult(data);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "暂时无法读取事件。");
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  const events = result?.events.filter(event => filter === "all" || event.kind === filter) ?? [];
  return <section className="finance-card a-share-events" aria-label="A 股专属事件">
    <div className="workbench-item-head"><h2>A 股专属事件</h2><span className="status-badge">只读证据</span></div>
    <p className="muted">{symbol} · 截至 {asOf}。查看近 30 天龙虎榜、近一年披露的股东增减持和限售解禁，以及有公告佐证的未来 90 天解禁。</p>
    <button type="button" className="chat-config-toggle" disabled={busy || !asOf} onClick={() => void preview()}>
      {busy && <LoaderCircle size={15} className="spin" />}{busy ? "核对事件…" : result ? "刷新事件" : "查看 A 股事件"}
    </button>
    {error && <p className="error-banner" role="alert">{error}</p>}
    {busy && !result && <p className="muted" role="status">正在核对交易日与公告。</p>}
    {result && <div aria-busy={busy}>
      <div className="event-filters" role="group" aria-label="筛选 A 股事件">
        {Object.entries(eventFilters).map(([key, label]) => <button key={key} type="button" className="chat-config-toggle"
          aria-pressed={filter === key} onClick={() => setFilter(key as keyof typeof eventFilters)}>{label}</button>)}
      </div>
      {events.some(event => event.kind === "holder_change") && <p className="field-note">
        股东增减持可能分阶段披露，股数应逐条查看。核对成功的记录另附发行人公告。
      </p>}
      {!events.length && <p className="muted" role="status">查询窗口内暂无符合校验的{filter === "all" ? "事件" : eventFilters[filter]}记录。</p>}
      {!!events.length && <ul className="review-checks">
        {events.map((event, index) => <li key={`${event.kind}:${event.date}:${index}`}>
          <div className="workbench-item-head"><strong>{event.date} · {event.title}</strong><span className="status-badge">{event.state}</span></div>
          <p>{event.description}</p><p className="muted">{event.kind === "holder_change" ? `公告日 ${event.published_at}` : event.note}</p>
          <div className="event-links">
            <a href={event.url} target="_blank" rel="noreferrer">{event.provider}原始记录 <ArrowUpRight size={12} /></a>
            {event.filing_url && <a href={event.filing_url} target="_blank" rel="noreferrer">{event.kind === "holder_change" ? "发行人公告" : `公告 · ${event.published_at}`} <ArrowUpRight size={12} /></a>}
          </div>
        </li>)}
      </ul>}
      {!!result.gaps.length && <details><summary>覆盖说明（{result.gaps.length}）</summary><ul>{result.gaps.map(gap => <li key={gap}>{gap}</li>)}</ul></details>}
    </div>}
  </section>;
}
