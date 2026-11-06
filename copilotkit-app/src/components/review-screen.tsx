"use client";

import { useT } from "@/hooks/use-language";

import { useState, type FormEvent } from "react";
import { ArrowUpRight, ListFilter } from "lucide-react";
import type { Review } from "./market-review";

const metrics = [
  { key: "day_pct", name: "当日涨跌", unit: "%", digits: 4 },
  { key: "relative_pct", name: "相对基准涨跌", unit: " 个百分点", digits: 4 },
  { key: "volume_ratio", name: "量比", unit: "×", digits: 3 },
] as const;
type Metric = typeof metrics[number]["key"];
type Condition = { metric: Metric; min: number | null; max: number | null };
type Status = "pass" | "missing" | "fail";
const labels = { pass: "全部满足", missing: "有缺数据", fail: "有不满足" };

function rangeText(condition: Condition, unit: string) {
  if (condition.min === null) return `≤ ${condition.max}${unit}`;
  if (condition.max === null) return `≥ ${condition.min}${unit}`;
  return `${condition.min} 至 ${condition.max}${unit}`;
}

export function ReviewScreen({ review, onResearch }: {
  review: Review;
  onResearch: (symbol: string, session: string, benchmark: string) => void;
}) {
  const t = useT();
  const [snapshot, setSnapshot] = useState<{ review: Review; conditions: Condition[] } | null>(null);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Status | "all">("all");
  const stale = dirty || snapshot?.review !== review;
  const results = snapshot?.review.symbols.slice().sort().map(symbol => {
    const row = snapshot.review.sample.find(item => item.symbol === symbol);
    const checks = snapshot.conditions.map(condition => {
      const value = row?.[condition.metric] ?? null;
      const status: Status = value === null ? "missing"
        : (condition.min !== null && value < condition.min) || (condition.max !== null && value > condition.max) ? "fail" : "pass";
      return { ...condition, value, status };
    });
    const status: Status = checks.some(check => check.status === "fail") ? "fail"
      : checks.some(check => check.status === "missing") ? "missing" : "pass";
    return { symbol, row, checks, status };
  }) ?? [];

  function check(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const conditions: Condition[] = [];
    for (const metric of metrics) {
      const minimum = String(data.get(`${metric.key}_min`) ?? "").trim();
      const maximum = String(data.get(`${metric.key}_max`) ?? "").trim();
      if (!minimum && !maximum) continue;
      const min = minimum ? Number(minimum) : null;
      const max = maximum ? Number(maximum) : null;
      if ((min !== null && !Number.isFinite(min)) || (max !== null && !Number.isFinite(max))) {
        setError("请输入有效的数值。");
        return;
      }
      if (min !== null && max !== null && min > max) {
        setError(`${metric.name}的下限应小于或等于上限。`);
        return;
      }
      conditions.push({ metric: metric.key, min, max });
    }
    if (!conditions.length) {
      setError("请至少填写一个条件的下限或上限。");
      return;
    }
    setSnapshot({ review, conditions });
    setDirty(false);
    setError("");
    setFilter("all");
  }

  return <section className="finance-card review-screen" aria-label={t("样本条件核对")}>
    <h2><ListFilter size={17} aria-hidden="true" />{t("样本条件核对")}</h2>
    <p className="muted">{t("核对")}{t(review.session)}{t("的")}{t(review.symbols.length)}{t("个样本。所有已填区间需同时满足，上下限均包含。留空的指标不参与核对。")}</p>
    <form onSubmit={check} onInput={() => setDirty(true)} onReset={() => { setSnapshot(null); setDirty(false); setError(""); }}>
      <div className="screen-condition-fields">
        {metrics.map(metric => <fieldset key={metric.key}>
          <legend>{t(metric.name)}（{t(metric.unit.trim())}）</legend>
          <label>{t("下限")}<input type="number" step="any" min={metric.key === "volume_ratio" ? 0 : undefined}
            aria-label={t(`${metric.name}下限`)} name={`${metric.key}_min`} placeholder={t("不限")} /></label>
          <label>{t("上限")}<input type="number" step="any" min={metric.key === "volume_ratio" ? 0 : undefined}
            aria-label={t(`${metric.name}上限`)} name={`${metric.key}_max`} placeholder={t("不限")} /></label>
        </fieldset>)}
      </div>
      <div className="workbench-actions">
        <button type="reset" className="chat-config-toggle">{t("清空条件")}</button>
        <button type="submit" className="primary-button">{t("核对条件")}</button>
      </div>
    </form>
    {error && <p className="error-banner" role="alert">{t(error)}</p>}
    {snapshot && <>
      <p className="field-note" role="status">{t(stale ? "行情或条件已修改，以下保留上次结果，请重新核对。" : "核对完成。")}{t("结果对应")}{t(snapshot.review.session)}{t("，基准")}{t(snapshot.review.benchmark.symbol)}。</p>
      <div className="event-filters" role="group" aria-label={t("按核对结果筛选")}>
        <button type="button" className="chat-config-toggle" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>{t("全部（")}{t(results.length)}）</button>
        {(["pass", "missing", "fail"] as const).map(status => <button type="button" className="chat-config-toggle" key={status}
          aria-pressed={filter === status} onClick={() => setFilter(status)}>{t(labels[status])}（{t(results.filter(result => result.status === status).length)}）</button>)}
      </div>
      <ul className="review-checks screen-results" aria-label={t("逐只条件核对结果")}>
        {results.filter(result => filter === "all" || filter === result.status).map(result => <li key={result.symbol}>
          <div className="workbench-item-head"><strong>{t(result.symbol)}</strong><span className={`status-badge screen-status-${result.status}`}>{t(labels[result.status])}</span></div>
          <ul className="screen-check-details">{result.checks.map(check => {
            const info = metrics.find(metric => metric.key === check.metric)!;
            return <li key={check.metric}>
              <span>{t(info.name)} · {t(rangeText(check, info.unit))}</span>
              <strong>{t(check.value === null ? "缺少数据" : `${check.value.toFixed(info.digits)}${info.unit}`)}</strong>
              <span>{t(check.status === "pass" ? "满足" : check.status === "fail" ? "不满足" : "待核对")}</span>
            </li>;
          })}</ul>
          {!result.row && <p className="muted">{t(snapshot.review.gaps.find(gap => gap.symbol === result.symbol)?.reason ?? "未取得与基准对齐的日线。")}</p>}
          <div className="candidate-observation-actions">
            {result.row && <a className="source-link" href={result.row.source} target="_blank" rel="noreferrer">{t(result.row.provider)}{t("行情来源")}<ArrowUpRight size={12} /></a>}
            <button type="button" className="chat-config-toggle" disabled={stale || !result.row}
              onClick={() => onResearch(result.symbol, snapshot.review.session, snapshot.review.benchmark.symbol)}>{t("研究该标的")}</button>
          </div>
        </li>)}
      </ul>
      {!results.some(result => filter === "all" || filter === result.status) && <p className="muted">{t("当前分类没有标的。")}</p>}
    </>}
    <p className="field-note">{t("核对基于未复权收盘日线。量比需要此前 20 个有成交日的数据，除权除息可能影响涨跌。全部满足表示通过已填条件。")}</p>
  </section>;
}
