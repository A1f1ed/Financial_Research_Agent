"use client";

import { useEffect, useRef, useState } from "react";
import { Archive, Check, FileText, Plus, RefreshCw, Search, X } from "lucide-react";
import { researchRequest } from "@/components/workbench-panels";
import { DocumentDialog } from "./detail";
import { DocumentUpload } from "./upload";
import { errorText, metadataFrom, sizeLabel, statusLabel, useDocumentCopy, kinds, type DocumentDetail, type DocumentSummary, type Metadata } from "./shared";

type Results = { documents: DocumentSummary[]; total: number; page: number; page_size: number };
function ArchiveDialog({ targets, restoring, removeFrom, onCancel, onDone }: { targets: DocumentSummary[]; restoring: boolean; removeFrom?: { id: string; revision: number }; onCancel: () => void; onDone: (failed: string[]) => void }) {
  const c = useDocumentCopy();
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [references, setReferences] = useState<number | null>(null);
  useEffect(() => {
    dialog.current?.showModal();
    const controller = new AbortController();
    void Promise.all(targets.map(item => researchRequest<DocumentDetail>(`documents/${item.id}`, "GET", undefined, controller.signal)))
      .then(items => { if (!controller.signal.aborted) setReferences(items.reduce((sum, item) => sum + item.reference_count, 0)); })
      .catch(err => { if (!controller.signal.aborted) setError(errorText(err, c)); });
    return () => { controller.abort(); dialog.current?.close(); };
  }, [targets, c]);
  async function apply() {
    setBusy(true); setError("");
    if (removeFrom) {
      try {
        await researchRequest(`knowledge/collections/${removeFrom.id}/members`, "POST", { expected_revision: removeFrom.revision, action: "remove", document_ids: targets.map(item => item.id) });
        onDone([]);
      } catch (err) { setError(errorText(err, c)); setBusy(false); }
      return;
    }
    const results = await Promise.allSettled(targets.map(item => researchRequest(`documents/${item.id}/${restoring ? "restore" : "archive"}`, "POST", {})));
    const failed = targets.filter((_, index) => results[index].status === "rejected").map(item => item.id);
    onDone(failed);
  }
  return <dialog ref={dialog} className="document-confirm-dialog" aria-label={c("Confirm document action", "确认资料操作")} onCancel={event => { if (busy) event.preventDefault(); else onCancel(); }}>
    <h2>{removeFrom ? c("Remove from this collection?", "从此集合移出资料？") : restoring ? c("Restore selected documents?", "恢复所选资料？") : c("Archive selected documents?", "归档所选资料？")}</h2>
    <p>{targets.length} {c("documents selected", "份资料已选")}</p><ul>{targets.map(item => <li key={item.id}>{item.title}</li>)}</ul>
    <p>{removeFrom ? c("Only this collection's membership changes. Original files, other collections, processing and historical citations are retained. You can add these versions again later.", "仅移出本集合。原文、其他集合、处理任务和历史引用均保留，之后可重新添加这些版本。") : restoring ? c("Restored documents become eligible for new research, subject to publication dates. Stopped processing must be retried separately.", "恢复后，资料可按公开日期规则用于新研究。已经停止的处理需要另行重试。")
      : c("New research will exclude these documents. In-progress processing will stop. Original files, existing reports and citation snapshots are retained.", "新研究不再使用这些资料，正在进行的处理会停止。原文、已有报告和引用快照会保留。")}</p>
    <p role="status">{references === null ? c("Checking citation impact…", "正在核对引用影响…") : `${references} ${c("existing citations retained", "条已有引用将保留")}`}</p>
    {error && <p role="alert">{error}</p>}
    <div className="workbench-actions"><button className="chat-config-toggle" disabled={busy} onClick={onCancel}>{c("Cancel", "取消")}</button>
      <button className={`primary-button ${removeFrom ? "danger-button" : ""}`} disabled={busy || references === null} onClick={() => void apply()}>{busy ? c("Applying…", "正在处理…") : removeFrom ? c("Remove from collection", "确认移出集合") : restoring ? c("Restore", "恢复归档") : c("Archive", "确认归档")}</button></div>
  </dialog>;
}

export function DocumentLibrary({ selectedId, selectedPage = 1, onSelect, onTask, collection, onCollectionChanged, onAddExisting }: { selectedId: string | null; selectedPage?: number; onSelect: (id: string | null) => void; onTask: (id: string) => void;
  collection?: { id: string; name: string; revision: number; archived: boolean }; onCollectionChanged?: () => void; onAddExisting?: () => void }) {
  const c = useDocumentCopy();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [symbol, setSymbol] = useState("");
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [archived, setArchived] = useState(false);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState<Results>({ documents: [], total: 0, page: 1, page_size: 20 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const [loadedScope, setLoadedScope] = useState("");
  const scope = JSON.stringify([query, kind, symbol, status, from, to, archived, page, collection?.id, collection?.revision]);
  const selectionReady = !loading && search === query && loadedScope === scope;
  const [confirmation, setConfirmation] = useState<DocumentSummary[] | null>(null);
  const [removing, setRemoving] = useState(false);
  const [upload, setUpload] = useState<{ key: string; metadata?: Metadata; previousId?: string } | null>(null);
  const refresh = () => { setRevision(value => value + 1); onCollectionChanged?.(); };
  useEffect(() => { setNotice(""); }, [c]);
  useEffect(() => { const timer = setTimeout(() => { setQuery(search); setPage(1); }, 250); return () => clearTimeout(timer); }, [search]);
  useEffect(() => { setSelected([]); }, [query, kind, symbol, status, from, to, archived, page, collection?.id, collection?.revision]);
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>; let pending = false;
    setLoading(true); setError("");
    const parameters = new URLSearchParams({ q: query, kind, archived: String(archived), page: String(page), page_size: "20" });
    if (symbol) parameters.set("symbol", symbol);
    if (status) parameters.set("status", status);
    if (from) parameters.set("published_from", from);
    if (to) parameters.set("published_to", to);
    if (collection?.id) parameters.set("collection_id", collection.id);
    if (!kind) parameters.delete("kind");
    const load = async () => {
      if (pending || controller.signal.aborted || document.hidden) return;
      pending = true; clearTimeout(timer); let active = false;
      try {
        const response = await researchRequest<Results>(`documents?${parameters}`, "GET", undefined, controller.signal);
        if (controller.signal.aborted) return;
        setResult(response); setLoadedScope(JSON.stringify([query, kind, symbol, status, from, to, archived, page, collection?.id, collection?.revision])); setError("");
        active = response.documents.some(item => ["queued", "processing"].includes(item.status));
      } catch (err) { if (!controller.signal.aborted) setError(errorText(err, c)); }
      finally { pending = false; if (!controller.signal.aborted) { setLoading(false); if (!document.hidden) timer = setTimeout(load, active ? 3000 : 15000); } }
    };
    const visibility = () => { if (document.hidden) clearTimeout(timer); else void load(); };
    document.addEventListener("visibilitychange", visibility); void load();
    return () => { controller.abort(); clearTimeout(timer); document.removeEventListener("visibilitychange", visibility); };
  }, [query, kind, symbol, status, from, to, archived, page, revision, c, collection?.id, collection?.revision]);
  const choose = (id: string) => setSelected(items => items.includes(id) ? items.filter(item => item !== id) : [...items, id]);
  const chosen = result.documents.filter(item => selected.includes(item.id));
  const version = (document: DocumentDetail) => { onSelect(null); setUpload({ key: crypto.randomUUID(), metadata: metadataFrom(document), previousId: document.id }); };
  return <div className="workbench-page document-library">
    <div className="workbench-title"><div>{collection ? <h2>{c("Documents in this collection", "集合中的资料")}</h2> : <><span className="section-eyebrow">RESEARCH MATERIAL</span><h1>{c("Document library", "研究资料")}</h1></>}<p className="intro">{collection ? c("Membership pins each file version. Adding a newer version retains older evidence until you explicitly remove it.", "集合绑定具体文件版本。添加新版本不会自动移除旧证据，需明确选择移出。") : c("Manage originals, publication dates, processing and file versions. Add new material whenever your research changes.", "管理原文、公开日期、处理状态和文件版本，随研究需要添加新资料。")}</p></div>
      <div className="workbench-actions">{onAddExisting && <button className="chat-config-toggle" disabled={collection?.archived} onClick={onAddExisting}>{c("Add existing", "添加已有资料")}</button>}<button className="primary-button" disabled={collection?.archived} onClick={() => setUpload({ key: crypto.randomUUID() })}><Plus size={16} />{c("Add documents", "添加资料")}</button></div></div>
    {upload && !collection?.archived && <DocumentUpload key={upload.key} initial={upload.metadata} previousId={upload.previousId} collectionId={collection?.id} onClose={() => setUpload(null)} onChanged={refresh} onOpen={onSelect} onTask={onTask} />}
    <div className="document-filter-bar">
      <label><span className="sr-only">{c("Search documents", "搜索资料")}</span><span className="document-search"><Search size={16} /><input placeholder={c("Search title or issuer", "搜索标题或发布机构")} value={search} onChange={event => setSearch(event.target.value)} /></span></label>
      <select aria-label={c("Filter material type", "筛选材料类型")} value={kind} onChange={event => { setKind(event.target.value); setPage(1); }}><option value="">{c("All material types", "全部材料类型")}</option>{Object.entries(kinds).map(([key, labels]) => <option key={key} value={key}>{c(labels[0], labels[1])}</option>)}</select>
      <select aria-label={c("Document archive view", "资料归档视图")} value={String(archived)} onChange={event => { setArchived(event.target.value === "true"); setPage(1); }}><option value="false">{c("Active library", "当前资料")}</option><option value="true">{c("Archived", "已归档")}</option></select>
      <button className="chat-config-toggle" onClick={refresh} aria-label={c("Refresh documents", "刷新资料")}><RefreshCw size={16} /></button>
    </div>
    <details className="document-more-filters"><summary>{c("Company, status & publication dates", "公司、状态与公开日期筛选")}</summary><div className="document-filter-bar">
      <label>{c("Symbol", "证券代码")}<input placeholder="1211.HK" value={symbol} onChange={event => { setSymbol(event.target.value.trim().toUpperCase()); setPage(1); }} /></label>
      <label>{c("Processing", "处理状态")}<select value={status} onChange={event => { setStatus(event.target.value); setPage(1); }}><option value="">{c("Any status", "全部状态")}</option>{["queued", "processing", "ready", "partial", "failed", "cancelled"].map(value => <option key={value} value={value}>{statusLabel(value, c)}</option>)}</select></label>
      <label>{c("Published from", "公开日期起日")}<input type="date" value={from} max={to || undefined} onChange={event => { setFrom(event.target.value); setPage(1); }} /></label>
      <label>{c("Published through", "公开日期止日")}<input type="date" value={to} min={from || undefined} onChange={event => { setTo(event.target.value); setPage(1); }} /></label>
    </div><small className="muted">{c("Publication date filters use Asia/Shanghai. Unknown publication dates are excluded when a date range is set.", "公开日期筛选采用 Asia/Shanghai 时区，设置日期范围时排除未知公开日期的资料。")}</small></details>
    {error && <p role="alert" className="error-banner">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {chosen.length > 0 && <div className="document-selection-bar"><span>{chosen.length} {c("selected on this page", "项已选（当前页）")}</span><button className="chat-config-toggle" disabled={!selectionReady} onClick={() => { setRemoving(false); setConfirmation(chosen); }}><Archive size={15} />{archived ? c("Restore selected", "恢复所选") : c("Archive selected", "归档所选")}</button>{collection && <button className="chat-config-toggle danger-button" disabled={!selectionReady || collection.archived} onClick={() => { setRemoving(true); setConfirmation(chosen); }}>{c("Remove from collection", "从集合移出")}</button>}<button className="chat-config-toggle" onClick={() => setSelected([])}><X size={14} />{c("Clear selection", "取消选择")}</button></div>}
    <div className="document-table" aria-busy={loading}>
      {result.documents.length > 0 && <div className="document-table-heading"><label><input type="checkbox" disabled={!selectionReady} aria-label={c("Select all documents on this page", "选择当前页全部资料")} checked={result.documents.every(item => selected.includes(item.id))} onChange={event => setSelected(event.target.checked ? result.documents.map(item => item.id) : [])} />{c("Material", "资料")}</label><span>{c("Publication / coverage", "公开时间 / 覆盖")}</span><span>{c("Processing", "处理状态")}</span></div>}
      {result.documents.map(item => <article key={item.id} className="document-table-row">
        <div className="document-title-cell"><input type="checkbox" disabled={!selectionReady} aria-label={c("Select ", "选择 ") + item.title} checked={selected.includes(item.id)} onChange={() => choose(item.id)} /><FileText size={22} /><div><button className="document-title-button" onClick={() => onSelect(item.id)}>{item.title}</button><small>{item.issuer || item.filename}{item.symbols.length ? ` · ${item.symbols.join(", ")}` : ""}</small><small>v{item.version} · {sizeLabel(item.byte_size)} · {item.page_count} {c("pages", "页")}</small></div></div>
        <div><time>{item.published_at ? new Date(item.published_at).toLocaleString() : item.published_on || c("Publication date unknown", "公开日期未知")}</time>{!item.published_on && !item.published_at && <small className="muted">{c("Excluded from strict as-of research", "严格历史研究中排除")}</small>}</div>
        <div><span className={`status-badge ${item.status}`}>{statusLabel(item.status, c)}</span><button className="chat-config-toggle" onClick={() => onSelect(item.id)}>{c("Open", "打开")}</button></div>
      </article>)}
      {!result.documents.length && <div className="document-empty"><FileText size={34} /><h2>{loading ? c("Loading documents…", "正在加载资料…") : query || kind || symbol || status || from || to ? c("No matching material", "没有匹配资料") : archived ? c("No archived documents", "没有已归档资料") : collection ? c("No documents in this collection", "此集合暂无资料") : c("Start with your first document", "从第一份资料开始")}</h2>
        <p>{c("Upload a report or image, or import a supported official link. No preloaded server folder is needed.", "上传报告或图片，或导入支持的官方链接，无需提前在服务器放置文件。")}</p>
        {!loading && !archived && !collection?.archived && <button className="primary-button" onClick={() => setUpload({ key: crypto.randomUUID() })}><Plus size={16} />{c("Add documents", "添加资料")}</button>}</div>}
    </div>
    <div className="document-pagination"><span>{result.total} {c("documents", "份资料")} · {c("Page", "第")} {page} / {Math.max(1, Math.ceil(result.total / result.page_size))}</span><div className="workbench-actions">
      <button className="chat-config-toggle" disabled={page <= 1 || loading} onClick={() => setPage(value => value - 1)}>{c("Previous", "上一页")}</button>
      <button className="chat-config-toggle" disabled={page * result.page_size >= result.total || loading} onClick={() => setPage(value => value + 1)}>{c("Next", "下一页")}</button></div></div>
    {confirmation && <ArchiveDialog targets={confirmation} restoring={archived} removeFrom={removing && collection ? collection : undefined} onCancel={() => setConfirmation(null)} onDone={failed => { setConfirmation(null); setSelected(failed); refresh(); setNotice(failed.length ? c("Some documents could not be updated. Failed items remain selected; refresh and retry.", "部分资料未能更新，失败项仍保留选择，请刷新后重试。") : c("Document action completed.", "资料操作已完成。")); }} />}
    {selectedId && <DocumentDialog key={`${selectedId}:${selectedPage}`} id={selectedId} initialPage={selectedPage} onClose={() => onSelect(null)} onChanged={refresh} onVersion={version} onSwitch={onSelect} onTask={onTask} />}
  </div>;
}
