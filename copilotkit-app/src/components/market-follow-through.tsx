"use client";

import { useT } from "@/hooks/use-language";

import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, LoaderCircle } from "lucide-react";
import { researchRequest } from "./workbench-panels";

type FollowThrough = {
  cohort_count: number | null;
  observed_count: number | null;
  up: number | null;
  flat: number | null;
  down: number | null;
  median: number | null;
  resealed: number | null;
  reseal_rate: number | null;
  groups: Array<{ label: string; count: number; observed: number; median: number | null }>;
  movers: Array<{ code: string; symbol: string | null; name: string; change: number; previous_days: number | null }>;
  sources: Array<{ label: string; url: string; verified?: boolean }>;
};

const pct = (value: number | null) => value === null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;

export function MarketFollowThrough({ session, previous, renderActions }: {
  session: string; previous: string; renderActions: (symbol: string, session: string) => React.ReactNode;
}) {
  const t = useT();
  const [result, setResult] = useState<FollowThrough | null>(null);
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
      const query = new URLSearchParams({ session, previous_session: previous });
      const data = await researchRequest<FollowThrough>(`market-follow-through?${query}`, "GET", undefined, controller.signal);
      if (!controller.signal.aborted) setResult(data);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "暂时无法读取次日表现。");
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return <section className="finance-card market-sentiment" aria-label={t("昨涨停股次日表现")} aria-busy={busy}>
    <div className="workbench-item-head"><h2>{t("昨涨停股次日表现")}</h2><span className="status-badge">{t(session)}</span></div>
    <p className="muted">{t("跟踪")}{t(previous)}{t("涨停名单在")}{t(session)}{t("的表现，按昨日连板层级分组。")}</p>
    <button type="button" className="chat-config-toggle" disabled={busy} onClick={() => void refresh()}>
      {busy && <LoaderCircle className="spin" size={14} />}{t(busy ? "核对次日行情…" : result ? "刷新次日表现" : "查看次日表现")}
    </button>
    {error && <p role="alert" className="error-banner">{t(error)}</p>}
    {busy && !result && <p className="muted" role="status">{t("正在核对相邻交易日与涨停名单。")}</p>}
    {result && <>
      <div className="review-metrics">
        <div><small>{t("可比较 / 昨日涨停")}</small><strong>{t(result.observed_count ?? "—")} / {t(result.cohort_count ?? "—")}</strong></div>
        <div><small>{t("上涨 / 平盘 / 下跌")}</small><strong>{t(result.up ?? "—")} / {t(result.flat ?? "—")} / {t(result.down ?? "—")}</strong></div>
        <div><small>{t("次日涨跌中位数")}</small><strong>{t(pct(result.median))}</strong></div>
        <div><small>{t("再度涨停")}</small><strong>{t(result.resealed ?? "—")}</strong>
          {result.reseal_rate !== null && <small>{t("占昨日样本")}{t(result.reseal_rate.toFixed(2))}%</small>}</div>
      </div>
      {result.observed_count === null && <p className="muted" role="status">{t("有行情池未通过日期核对，相关指标暂不可用。")}</p>}
      {!!result.groups.length && <ul className="review-checks">{result.groups.map(group => <li key={group.label} className="workbench-item-head">
        <strong>{t(group.label)}</strong><span>{t("覆盖")}{t(group.observed)}/{t(group.count)}{t("· 中位数")}{t(pct(group.median))}</span>
      </li>)}</ul>}
      {!!result.movers.length && <details><summary>{t("查看涨跌两端标的")}</summary>
        <ul className="review-checks">{result.movers.map(row => <li key={row.code} className="workbench-item-head">
          <span><strong>{t(row.name)}</strong> · {t(row.symbol ?? row.code)} · {t(pct(row.change))}
            {t(row.previous_days !== null && ` · 昨日 ${row.previous_days} 板`)}</span>
          {t(row.symbol && renderActions(row.symbol, session))}
        </li>)}</ul>
      </details>}
      <details><summary>{t("核对口径与来源")}</summary>
        <p className="field-note">{t("涨跌按两份名单相交的样本计算。再次涨停按上一日与当日涨停池交集计算，分母为上一日涨停池。参考 ETF 日线用于确认日期相邻。")}</p>
        <ul className="review-checks">{result.sources.map(source => <li key={source.label}>
          <a href={source.url} target="_blank" rel="noreferrer">{t(source.label)} <ArrowUpRight size={12} /></a>
          {source.verified === false && <p className="muted">{t("未能核对")}</p>}
        </li>)}</ul>
      </details>
    </>}
  </section>;
}
