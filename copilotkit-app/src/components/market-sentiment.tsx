"use client";

import { useT } from "@/hooks/use-language";

import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, LoaderCircle } from "lucide-react";
import { researchRequest } from "./workbench-panels";

type Pool = { label: string; count: number | null; source: string; sample: Array<{ symbol: string; close: number; source: string }> };
type Sentiment = {
  pools: Record<string, Pool>; break_rate: number | null;
  ladder: Array<{ days: number; count: number }>;
  industries: Array<{ name: string; count: number }>;
  leaders: Array<{ code: string; symbol: string | null; name: string; days: number; industry: string }>;
};

export function MarketSentiment({ session, renderActions }: {
  session: string; renderActions: (symbol: string, session: string) => React.ReactNode;
}) {
  const t = useT();
  const [result, setResult] = useState<Sentiment | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);

  async function refresh() {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError("");
    try {
      const value = await researchRequest<Sentiment>(`market-sentiment?session=${encodeURIComponent(session)}`, "GET", undefined, controller.signal);
      if (!controller.signal.aborted) setResult(value);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "暂时无法读取行情池。");
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return <section className="finance-card market-sentiment" aria-label={t("市场情绪复盘")} aria-busy={busy}>
    <div className="workbench-item-head"><h2>{t("市场情绪复盘")}</h2><span className="status-badge">{t(session)}</span></div>
    <p className="muted">{t("查看东方财富收盘行情池。每个非空池抽样对照腾讯日线，确认日期、收盘价与涨跌幅。")}</p>
    <button type="button" className="chat-config-toggle" disabled={busy} onClick={() => void refresh()}>
      {busy && <LoaderCircle size={14} className="spin" />}{t(busy ? "核对行情池…" : result ? "刷新情绪数据" : "查看涨跌停与连板")}
    </button>
    {error && <p role="alert" className="error-banner">{t(error)}</p>}
    {busy && !result && <p role="status" className="muted">{t("正在读取行情池并核对样本日期。")}</p>}
    {result && <>
      {Object.values(result.pools).every(pool => pool.count === null) && <p className="muted" role="status">{t("这一天的行情池尚未通过日期核对。可以换一个已收盘交易日再试。")}</p>}
      <div className="review-metrics">
        {Object.values(result.pools).map(pool => <div key={pool.label}><small>{t(pool.label)}</small><strong>{t(pool.count === null ? "—" : pool.count)}</strong>
          {pool.count === null && <small>{t("未能核对")}</small>}</div>)}
        <div><small>{t("池内炸板比例")}</small><strong>{t(result.break_rate === null ? "—" : `${result.break_rate}%`)}</strong></div>
      </div>
      {!!result.ladder.length && <div className="sentiment-breakdown">
        <div><h3>{t("连板梯队")}</h3><ul>{result.ladder.map(item => <li key={item.days}>{t(item.days)}{t("板 ·")}{t(item.count)}{t("只")}</li>)}</ul></div>
        <div><h3>{t("涨停池行业分布")}</h3><ul>{result.industries.map(item => <li key={item.name}>{t(item.name)} · {t(item.count)}{t("只")}</li>)}</ul></div>
      </div>}
      {!!result.leaders.length && <details><summary>{t("查看连板标的（")}{t(result.leaders.length)}）</summary>
        <ul className="review-checks">{result.leaders.map(row => <li key={row.code} className="workbench-item-head">
          <span><strong>{t(row.name)}</strong> · {t(row.symbol ?? row.code)} · {t(row.days)}{t("板")}</span>
          {t(row.symbol && renderActions(row.symbol, session))}
        </li>)}</ul>
      </details>}
      <details><summary>{t("核对口径与来源")}</summary>
        <p className="field-note">{t("计数采用东方财富行情池口径。炸板比例为炸板池 ÷（涨停池 + 炸板池），只有两个池均可核对且名单无重叠时才显示。行业沿用数据源分类。")}</p>
        <ul className="review-checks">{Object.values(result.pools).map(pool => <li key={pool.label}>
          <div className="event-links"><a href={pool.source} target="_blank" rel="noreferrer">{t(pool.label)}{t("原始记录")}<ArrowUpRight size={12} /></a>
            {pool.sample.map(row => <a key={row.symbol} href={row.source} target="_blank" rel="noreferrer">{t(row.symbol)}{t("日线 ·")}{t(row.close)} <ArrowUpRight size={12} /></a>)}
          </div>
          {pool.count === null && <p className="muted">{t("缺少可确认该交易日的完整记录。")}</p>}
        </li>)}</ul>
      </details>
    </>}
  </section>;
}
