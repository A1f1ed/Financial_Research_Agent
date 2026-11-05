"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowUpRight, LoaderCircle } from "lucide-react";
import { researchRequest, useResearchList } from "./workbench-panels";

type ReportOrigin = { report_id: string; condition_index: number; condition: string };
export type CheckSeed = { symbol: string; benchmark: string; baseline: string; report_origin?: ReportOrigin };
const metrics = {
  day_pct: { label: "单日涨跌", unit: "%" },
  relative_pct: { label: "相对基准涨跌", unit: " 个百分点" },
  volume_ratio: { label: "量比", unit: "×" },
};
type Metric = keyof typeof metrics;
type Evidence = { provider: string; source: string; symbol: string };
type Check = CheckSeed & {
  id: string;
  metric: Metric;
  direction: "gte" | "lte";
  threshold: number;
  note: string;
  message?: string | null;
  target_session?: string | null;
  next_attempt_at?: string | null;
  last_checked_at?: string;
  result: null | {
    session: string; value: number; met: boolean; retrospective: boolean; observation: Evidence; benchmark: Evidence;
    trigger?: "auto" | "manual"; calendar_source?: string;
  };
};

export function ReviewChecks({ visible, seed, onDismiss, onOpenReport }: {
  visible: boolean;
  seed: CheckSeed | null;
  onDismiss: (seed: CheckSeed) => void;
  onOpenReport: (id: string, index: number) => void;
}) {
  const { items: checks, loading, error: loadError, refresh } = useResearchList<Check>(visible ? "review-checks" : null, "checks");
  const [error, setError] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [metric, setMetric] = useState<Metric | "">("day_pct");
  const form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (visible && seed) form.current?.scrollIntoView({ block: "nearest" });
  }, [seed, visible]);
  useEffect(() => {
    setMetric(seed?.report_origin ? "" : "day_pct");
    setError("");
  }, [seed]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!seed || !metric || pending) return;
    const fields = new FormData(event.currentTarget);
    setPending("create");
    setError("");
    try {
      const { report_origin, ...scope } = seed;
      await researchRequest<Check>("review-checks", "POST", {
        ...scope, metric, direction: fields.get("direction"), threshold: Number(fields.get("threshold")), note: fields.get("note"),
        ...(report_origin && { report_origin: { report_id: report_origin.report_id, condition_index: report_origin.condition_index } }),
      });
      await refresh();
      onDismiss(seed);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "保存失败。"); }
    finally { setPending(null); }
  }

  async function verify(check: Check) {
    if (pending) return;
    setPending(check.id);
    setError("");
    try {
      await researchRequest<Check>(`review-checks/${check.id}/verify`, "POST", {});
      await refresh();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "验证失败。"); }
    finally { setPending(null); }
  }

  async function remove(id: string) {
    if (pending) return;
    setPending(id);
    setError("");
    try {
      await researchRequest(`review-checks/${id}`, "DELETE");
      await refresh();
      setDeleteTarget(null);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "删除失败。"); }
    finally { setPending(null); }
  }

  return <section className="finance-card" aria-label="研究条件验证">
    <h2>下一交易日验证</h2>
    <p className="muted">从复盘样本或研究报告保存条件。服务运行时会在下一交易日北京时间 15:15 后自动核对，缺数时保留待验证状态。目标日 09:15 及以后保存的条件标为事后记录。</p>
    {seed && <form key={`${seed.symbol}:${seed.baseline}:${seed.report_origin?.report_id}:${seed.report_origin?.condition_index}`} className="review-check-form" ref={form} onSubmit={create}>
      <h3>{seed.symbol} · 以 {seed.baseline} 为基线</h3>
      {seed.report_origin && <div className="review-report-origin">
        <strong>报告原文</strong><p>{seed.report_origin.condition}</p>
        <p className="field-note">基准 {seed.benchmark}。请选择可用日线核对的指标与阈值。自动核对只评估你保存的量化条件。</p>
      </div>}
      <fieldset disabled={pending !== null || loading}>
        <div className="form-grid">
          <label>验证指标<select required value={metric} onChange={e => setMetric(e.target.value as Metric | "")}>
            {seed.report_origin && <option value="" disabled>请选择验证指标</option>}
            {Object.entries(metrics).map(([value, info]) => <option key={value} value={value} disabled={value === "relative_pct" && seed.symbol === seed.benchmark}>{info.label}</option>)}
          </select></label>
          <label>比较条件<select name="direction" required defaultValue={seed.report_origin ? "" : "gte"}>
            {seed.report_origin && <option value="" disabled>请选择比较条件</option>}
            <option value="gte">大于或等于</option><option value="lte">小于或等于</option></select></label>
          <label>阈值{metric && `（${metrics[metric].unit.trim()}）`}<input name="threshold" type="number" step="any" min={metric === "volume_ratio" ? 0 : -100} max={100} required /></label>
          <label>研究备注<input name="note" maxLength={160} placeholder="可选，记录假设或依据" /></label>
        </div>
      </fieldset>
      <div className="workbench-actions">
        <button type="button" className="chat-config-toggle" disabled={pending === "create"} onClick={() => {
          onDismiss(seed);
          if (seed.report_origin) onOpenReport(seed.report_origin.report_id, seed.report_origin.condition_index);
        }}>{seed.report_origin ? "取消并返回报告" : "取消"}</button>
        <button type="submit" className="primary-button" disabled={pending !== null || loading || !metric}>{pending === "create" ? "保存中…" : "保存验证条件"}</button>
      </div>
    </form>}
    {error && <p role="alert" className="error-banner">{error}</p>}
    {loadError && <div className="workbench-actions"><span role="alert">无法读取验证条件。</span><button type="button" className="chat-config-toggle" onClick={() => void refresh()}>重试</button></div>}
    {loading && <p className="muted" role="status">正在读取已保存条件…</p>}
    {!loading && !loadError && !checks.length && <p className="muted">暂时没有已保存的条件。</p>}
    <ul className="review-checks">
      {checks.map(check => {
        const info = metrics[check.metric];
        const result = check.result;
        const origin = check.report_origin;
        return <li key={check.id}>
          <div className="workbench-item-head">
            <strong>{check.symbol} · {info.label} {check.direction === "gte" ? "≥" : "≤"} {check.threshold}{info.unit}</strong>
            <span className={`status-badge${result?.met === false ? " failed" : ""}`}>{result ? result.met ? "达到条件" : "未达到" : "待验证"}</span>
          </div>
          <p className="muted">基线 {check.baseline} · 基准 {check.benchmark}
            {!result && check.target_session && ` · 目标日 ${check.target_session}`}
            {result && ` · ${result.retrospective ? "事后记录" : "事前记录"}`}
            {result?.trigger && ` · ${result.trigger === "auto" ? "自动核对" : "手动核对"}`}</p>
          {check.note && <p>{check.note}</p>}
          {origin && <details className="review-report-origin"><summary>来源报告中的失效条件</summary>
            <p>{origin.condition}</p>
            <button type="button" className="chat-config-toggle" onClick={() => onOpenReport(origin.report_id, origin.condition_index)}>
              查看来源报告 <ArrowUpRight size={12} />
            </button>
          </details>}
          {check.message && <p role="status">{check.message}</p>}
          {!result && check.next_attempt_at && check.last_checked_at && <p className="field-note">下一次自动核对 <time dateTime={check.next_attempt_at}>
            {new Date(check.next_attempt_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit",
              day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })}</time>（北京时间）</p>}
          {!result && check.next_attempt_at === null && <p className="field-note">已停止自动重试，可手动核对。</p>}
          {result && <p>{result.session} 实测 <strong>{result.value.toLocaleString("zh-CN", { maximumFractionDigits: 4 })}{info.unit}</strong>
            {" · "}<a href={result.observation.source} target="_blank" rel="noreferrer">{result.observation.provider} <ArrowUpRight size={12} /></a>
            {check.metric === "relative_pct" && <> · <a href={result.benchmark.source} target="_blank" rel="noreferrer">基准 {result.benchmark.provider}</a></>}
            {result.calendar_source && <> · <a href={result.calendar_source} target="_blank" rel="noreferrer">交易日历 <ArrowUpRight size={12} /></a></>}
          </p>}
          <div className="workbench-actions">
            {!result && <button type="button" className="chat-config-toggle" disabled={pending !== null} onClick={() => void verify(check)}>
              {pending === check.id && deleteTarget !== check.id && <LoaderCircle size={14} className="spin" />}
              {pending === check.id && deleteTarget !== check.id ? "核对中…" : "核对收盘数据"}
            </button>}
            <button type="button" className="chat-config-toggle danger-button" aria-expanded={deleteTarget === check.id}
              disabled={pending !== null} onClick={() => setDeleteTarget(check.id)}>删除条件</button>
          </div>
          {deleteTarget === check.id && <div className="delete-confirmation">
            <p>删除这条条件及其验证结果？</p>
            <div className="workbench-actions">
              <button type="button" className="chat-config-toggle" disabled={pending !== null} onClick={() => setDeleteTarget(null)}>取消</button>
              <button type="button" className="chat-config-toggle danger-button danger-confirm" disabled={pending !== null}
                onClick={() => void remove(check.id)}>确认删除</button>
            </div>
          </div>}
        </li>;
      })}
    </ul>
  </section>;
}
