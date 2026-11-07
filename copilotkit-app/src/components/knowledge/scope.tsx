"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ShieldCheck } from "lucide-react";
import { researchRequest } from "@/components/workbench-panels";
import { errorText, useDocumentCopy } from "@/components/documents/shared";
import type { Collection } from "./shared";

type ScopeResult = { eligible_count: number; excluded_count: number; timezone: string; scope_fingerprint: string;
  documents: { id: string; version: number; title: string; eligible: boolean; exclusion: string | null; warning: string | null }[] };

export function CollectionScope({ collection, onDocument }: { collection: Collection; onDocument: (id: string) => void }) {
  const c = useDocumentCopy();
  const [date, setDate] = useState(() => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Hong_Kong" }));
  const [instant, setInstant] = useState(""); const [market, setMarket] = useState("HK"); const [mode, setMode] = useState("strict");
  const [result, setResult] = useState<{ key: string; data: ScopeResult } | null>(null); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  const key = JSON.stringify([collection.id, collection.revision, collection.material_revision, date, instant, market, mode]);
  useEffect(() => { request.current?.abort(); setBusy(false); setError(""); return () => request.current?.abort(); }, [key]);
  async function check(event: React.FormEvent) {
    event.preventDefault(); request.current?.abort(); const controller = new AbortController(); request.current = controller; setBusy(true); setError("");
    try {
      const data = await researchRequest<ScopeResult>("knowledge/scope", "POST", { collection_ids: [collection.id], market, mode, ...(instant ? { as_of_at: instant } : { as_of: date }) }, controller.signal);
      if (!controller.signal.aborted) setResult({ key, data });
    } catch (err) { if (!controller.signal.aborted) setError(errorText(err, c)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  const current = result?.key === key ? result.data : null;
  const reasons: Record<string, [string, string]> = { original_removed: ["Original removed", "原文已移除"], document_archived: ["Document archived", "资料已归档"], published_after_cutoff: ["Published after the cutoff", "晚于截止日期公开"], publication_precision_insufficient: ["Day-only publication cannot establish this instant", "仅公开日不能支持该日内时刻断言"], publication_unknown: ["Publication date unverified", "公开日期未核实"] };
  return <details className="finance-card collection-scope"><summary><ShieldCheck size={17} />{c("Check research scope & cutoff", "检查研究范围与截止日期")}</summary>
    <p className="muted">{c("Check which exact versions satisfy the chosen dates. This reads membership and source metadata; it does not run research or a model.", "检查哪些具体版本符合日期范围。仅核对集合成员与来源信息，不会开始研究或调用模型。")}</p>
    <form onSubmit={check}><div className="form-grid">
      <label>{c("Information cutoff date", "信息截止日期")}<input required={!instant} disabled={!!instant} type="date" value={date} onChange={event => setDate(event.target.value)} /></label>
      <label>{c("Market timezone", "市场时区")}<select value={market} onChange={event => setMarket(event.target.value)}><option value="HK">HK · Asia/Hong_Kong</option><option value="US">US · America/New_York</option><option value="SH">SH · Asia/Shanghai</option><option value="SZ">SZ · Asia/Shanghai</option><option value="SG">SG · Asia/Singapore</option></select></label>
      <label>{c("Date policy", "日期规则")}<select value={mode} onChange={event => setMode(event.target.value)}><option value="strict">{c("Strict · exclude unknown publication dates", "严格 · 排除未知公开日期")}</option><option value="explore">{c("Explore · include unknown dates with warnings", "探索 · 纳入未知日期并持续提示")}</option></select></label>
      <label>{c("Exact instant (optional, with timezone)", "准确时刻（可选，须含时区）")}<input placeholder="2026-10-31T16:00:00+08:00" value={instant} onChange={event => setInstant(event.target.value)} /></label>
    </div>{mode === "explore" && <p className="coverage-warning">{c("Unknown publication dates may be included. This scope cannot be labelled strict historical research.", "可能纳入未知公开日期的资料，此范围不能标为严格历史研究。")}</p>}
      <button className="chat-config-toggle" disabled={busy || collection.archived}>{busy ? c("Checking…", "正在检查…") : c("Check scope", "检查范围")}</button>
    </form>{error && <p role="alert" className="error-banner">{error}</p>}
    {current && <div className="collection-scope-result"><p role="status">{current.eligible_count} {c("date-eligible", "项符合日期")} · {current.excluded_count} {c("excluded", "项排除")} · {current.timezone}</p>
      <ul>{current.documents.map(item => <li key={item.id}><button className="document-title-button" onClick={() => onDocument(item.id)}>{item.title} · v{item.version}</button><span data-eligible={item.eligible}>{item.eligible && !item.warning ? <><Check size={13} />{c("Eligible by date", "符合日期条件")}</> : reasons[item.exclusion || item.warning || ""] ? c(...reasons[item.exclusion || item.warning || ""]) : item.exclusion}</span></li>)}</ul>
      {!current.documents.length && <p>{c("This collection has no document versions.", "此集合没有文档版本。")}</p>}
      <small className="muted">{c("Date eligibility does not establish extraction, indexing or factual support. Review page coverage and evidence before using a source.", "符合日期不等于已完成提取、索引或支持结论，使用前仍需检查页面覆盖与证据。")}</small>
    </div>}
  </details>;
}
