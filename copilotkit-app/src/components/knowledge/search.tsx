"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, Database, LoaderCircle, RefreshCw, Search } from "lucide-react";
import { researchRequest } from "@/components/workbench-panels";
import { useDocumentCopy } from "@/components/documents/shared";
import type { Collection } from "./shared";

type Index = { id: string; document_id: string; job_id: string; mode: string; status: string; published: boolean; chunk_count: number; omitted_pages: number; error?: string };
type Hit = { citation_id: string; document_id: string; title: string; document_version: number; page_number: number; quote: string; published_on: string | null; published_at: string | null; publication_warning: string | null };
type Result = { id: string; query: string; search_mode: string; hits: Hit[]; elapsed_ms: number; created_at: string; gaps: { title?: string; reason: string; pages?: number }[]; scope: { eligible_count: number; excluded_count: number } };
type Material = { id: string; title: string; archived: boolean; status: string };
const indexStatuses: Record<string, [string, string]> = { queued: ["Queued", "排队中"], running: ["Running", "运行中"], complete: ["Complete", "已完成"], failed: ["Failed", "失败"], cancelled: ["Cancelled", "已停止"] };

export function CollectionSearch({ collection, onDocument, onTask }: { collection: Collection; onDocument: (id: string, page: number) => void; onTask: (id: string) => void }) {
  const c = useDocumentCopy(); const [documents, setDocuments] = useState<Material[]>([]); const [total, setTotal] = useState(0); const [indices, setIndices] = useState<Index[]>([]);
  const [selected, setSelected] = useState<string[]>([]); const [mode, setMode] = useState("keyword"); const [verified, setVerified] = useState(false);
  const [query, setQuery] = useState(""); const [date, setDate] = useState(() => new Date().toLocaleDateString("en-CA")); const [market, setMarket] = useState("HK");
  const [result, setResult] = useState<Result | null>(null); const [busy, setBusy] = useState(""); const [error, setError] = useState(""); const [revision, setRevision] = useState(0);
  const [indexPage, setIndexPage] = useState(1); const [loadedPage, setLoadedPage] = useState("");
  const pageKey = `${collection.id}:${collection.revision}:${indexPage}`;
  const controller = useRef<AbortController | null>(null); const sequence = useRef(0);
  const identity = `${collection.id}:${collection.revision}:${collection.material_revision}:${date}:${market}:${mode}:${query}`;
  const identityRef = useRef(identity); identityRef.current = identity; const [resultIdentity, setResultIdentity] = useState("");
  useEffect(() => { let active = true; let fetching = false; let timer: ReturnType<typeof setTimeout>; const abort = new AbortController();
    async function load() {
      if (fetching) return; fetching = true;
      try {
        const [materials, capability] = await Promise.all([
          researchRequest<{ documents: Material[]; total: number }>(`documents?collection_id=${collection.id}&page=${indexPage}&page_size=20`, "GET", undefined, abort.signal),
          researchRequest<{ verified: boolean }>("knowledge/embedding", "GET", undefined, abort.signal),
        ]);
        if (!active) return; setDocuments(materials.documents); setTotal(materials.total); setVerified(capability.verified);
        setSelected(values => values.filter(id => materials.documents.some(item => item.id === id)));
        if (materials.documents.length) {
          const params = new URLSearchParams(); materials.documents.forEach(item => params.append("document_id", item.id));
          const snapshot = await researchRequest<{ indices: Index[] }>(`knowledge/indices?${params}`, "GET", undefined, abort.signal);
          if (active) { setIndices(snapshot.indices); setLoadedPage(pageKey); }
        } else { setIndices([]); setLoadedPage(pageKey); }
      } catch (err) { if (active) setError(err instanceof Error ? err.message : String(err)); }
      finally { fetching = false; }
      if (active && document.visibilityState === "visible") timer = setTimeout(load, 5000);
    }
    const visible = () => { clearTimeout(timer); if (document.visibilityState === "visible") void load(); };
    document.addEventListener("visibilitychange", visible);
    void load(); return () => { active = false; abort.abort(); clearTimeout(timer); document.removeEventListener("visibilitychange", visible); };
  }, [collection.id, collection.revision, revision, indexPage, pageKey]);
  useEffect(() => () => { sequence.current++; controller.current?.abort(); }, []);
  async function build(force = false) {
    setBusy("index"); setError("");
    try { await researchRequest("knowledge/indices", "POST", { document_ids: selected, mode, force }); setRevision(value => value+1); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(""); }
  }
  async function search() {
    controller.current?.abort(); const abort = new AbortController(); controller.current = abort; const version = ++sequence.current; const atStart = identity;
    setBusy("search"); setError(""); setResult(null);
    try {
      const value = await researchRequest<Result>("knowledge/search", "POST", { collection_ids: [collection.id], as_of: date, market, mode: "strict", search_mode: mode, query, limit: 5 }, abort.signal);
      if (sequence.current === version && identityRef.current === atStart) { setResult(value); setResultIdentity(atStart); }
    } catch (err) { if (!abort.signal.aborted && identityRef.current === atStart) setError(err instanceof Error ? err.message : String(err)); }
    finally { if (sequence.current === version) setBusy(""); }
  }
  const visibleResult = resultIdentity === identity ? result : null;
  return <section className="finance-card knowledge-search">
    <div className="workbench-item-head"><h2><Search size={19} />{c("Search original evidence", "检索原文证据")}</h2><button className="chat-config-toggle" aria-label={c("Refresh indices", "刷新索引")} onClick={() => setRevision(value => value+1)}><RefreshCw size={14} /></button></div>
    <p className="muted">{c("Build an index for selected versions, then retrieve page-level excerpts within this collection and cutoff. Search does not generate a financial answer.", "先为选定版本建索引，再按本集合和截止日期检索原页摘录。搜索不会生成金融结论。")}</p>
    {error && <p role="alert" className="error-banner">{error}</p>}
    <label>{c("Retrieval mode", "检索模式")}<select value={mode} disabled={!!busy} onChange={event => setMode(event.target.value)}><option value="keyword">{c("Keyword · no model calls", "关键词 · 不调用模型")}</option><option value="hybrid" disabled={!verified}>{c("Hybrid · keywords + semantic vectors", "混合 · 关键词与语义向量")}</option></select></label>
    {!verified && <p className="field-note">{c("Hybrid mode requires a saved, successful embedding test in Settings → AI settings.", "混合模式需先在个人设置 → AI 设置中保存并通过 embedding 测试。")}</p>}
    <details className="knowledge-index-list"><summary><Database size={15} />{c("Index versions & processing", "索引版本与处理")}</summary>
      {documents.map(item => <div className="knowledge-index-row" key={item.id}><label><input type="checkbox" disabled={!!busy || loadedPage !== pageKey || collection.archived || item.archived || !["ready", "partial"].includes(item.status)} checked={selected.includes(item.id)} onChange={() => setSelected(values => values.includes(item.id) ? values.filter(id => id !== item.id) : [...values, item.id])} />{item.title}</label>
        {!indices.some(index => index.document_id === item.id) && <small className="knowledge-index-detail">{c("No index built for this version", "此版本尚未建立索引")}</small>}
        {indices.filter(index => index.document_id === item.id).slice(0,3).map(index => <div className="knowledge-index-detail" key={index.id}><span>{index.mode === "hybrid" ? c("Hybrid", "混合") : c("Keyword", "关键词")} · {indexStatuses[index.status] ? c(...indexStatuses[index.status]) : index.status} · {index.chunk_count} {c("chunks", "片段")}{index.published ? c(" · current", " · 当前版本") : ""}</span>{index.omitted_pages > 0 && <small>{index.omitted_pages} {c("pages not text-readable", "页非文字可读")}</small>}<button className="chat-config-toggle" onClick={() => onTask(index.job_id)}>{c("View task", "查看任务")}<ArrowUpRight size={13} /></button></div>)}
      </div>)}
      {total > 20 && <div className="document-pagination"><span>{c("Page", "页")} {indexPage} / {Math.ceil(total/20)}</span><button className="chat-config-toggle" disabled={!!busy || indexPage <= 1} onClick={() => { setSelected([]); setIndexPage(page => page-1); }}>{c("Previous", "上一页")}</button><button className="chat-config-toggle" disabled={!!busy || indexPage*20 >= total} onClick={() => { setSelected([]); setIndexPage(page => page+1); }}>{c("Next", "下一页")}</button></div>}
      <div className="workbench-actions"><button className="primary-button" disabled={!!busy || loadedPage !== pageKey || !selected.length || collection.archived} onClick={() => void build()}>{c("Build selected indices", "为所选资料建索引")}</button><button className="chat-config-toggle" disabled={!!busy || loadedPage !== pageKey || !selected.length || collection.archived} onClick={() => void build(true)}>{c("Rebuild selected", "重建所选索引")}</button></div>
    </details>
    <form onSubmit={event => { event.preventDefault(); void search(); }}>
      <fieldset disabled={!!busy || collection.archived}><div className="form-grid">
        <label>{c("Evidence cutoff date", "证据截止日期")}<input required type="date" value={date} onChange={event => setDate(event.target.value)} /></label>
        <label>{c("Market timezone", "市场时区")}<select value={market} onChange={event => setMarket(event.target.value)}>{["HK","US","SH","SZ","SG"].map(value => <option key={value}>{value}</option>)}</select></label>
        <label className="document-wide">{c("Find a disclosure or metric", "查找披露或指标")}<input required minLength={2} maxLength={500} value={query} onChange={event => setQuery(event.target.value)} placeholder={c("e.g. operating cash flow, impairment, sales volume", "例如：经营现金流、减值、销量")} /></label>
      </div><button className="primary-button" type="submit" disabled={!query.trim() || !!busy}>{busy === "search" ? <LoaderCircle className="spin" size={16} /> : <Search size={16} />}{c("Search evidence", "检索证据")}</button></fieldset>
    </form>
    {visibleResult && <div aria-live="polite" className="knowledge-search-results"><p>{visibleResult.scope.eligible_count} {c("eligible versions", "个合规版本")} · {visibleResult.scope.excluded_count} {c("excluded by scope/date", "个被范围/日期排除")} · {visibleResult.elapsed_ms.toFixed(0)} ms</p>
      {!visibleResult.hits.length && <p>{c("No matching excerpts. Review the query, cutoff and index coverage; this does not establish that a fact is absent from the originals.", "未检索到匹配摘录。请检查问题、日期与索引覆盖；这不能证明原文不存在该事实。")}</p>}
      {visibleResult.hits.map(hit => <article className="knowledge-hit" key={hit.citation_id}><div className="workbench-item-head"><strong>[{hit.citation_id}] {hit.title}</strong><button className="chat-config-toggle" onClick={() => onDocument(hit.document_id, hit.page_number)}>{c("Open original", "打开原文")} · p{hit.page_number}</button></div><small>v{hit.document_version} · PDF {hit.page_number} · {hit.published_at || hit.published_on || c("Publication unknown", "公开日期未知")}</small><blockquote>{hit.quote}</blockquote></article>)}
      {visibleResult.gaps.length > 0 && <div className="coverage-warning">{c("Coverage gaps", "覆盖缺口")}: {visibleResult.gaps.map((gap,i) => <p key={i}>{gap.title || ""} {gap.reason === "matching_index_missing" ? c("Matching index missing", "缺少匹配索引") : c(`${gap.pages} pages not text-readable`, `${gap.pages} 页非文字可读`)}</p>)}</div>}
      <small className="muted">{c("Saved search", "已保存检索")}: {visibleResult.id} · {c("Source candidates, not a generated financial conclusion.", "以上为原文候选证据，并非生成的金融结论。")}</small>
    </div>}
  </section>;
}
