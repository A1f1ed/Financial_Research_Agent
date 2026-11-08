"use client";

import { useEffect, useRef, useState } from "react";
import { Archive, ChevronLeft, ChevronRight, Download, ExternalLink, FilePlus2, LoaderCircle, RefreshCw, X } from "lucide-react";
import { researchRequest } from "@/components/workbench-panels";
import { MetadataFields, metadataFrom, metadataPayload, errorText, statusLabel, sizeLabel, useDocumentCopy, type DocumentDetail, type Metadata } from "./shared";

type Page = { text: string; status: string; error_type?: string; extraction_version?: string };
type Revision = { revision: number; created_at: string; reason: string; metadata: Record<string, unknown> };
export function DocumentDialog({ id, initialPage = 1, onClose, onChanged, onVersion, onSwitch, onTask, readOnly = false, citation }: {
  id: string; onClose: () => void; onChanged: () => void; onVersion: (document: DocumentDetail) => void;
  onSwitch: (id: string) => void; onTask: (id: string) => void; initialPage?: number; readOnly?: boolean;
  citation?: { quote: string; published_at?: string | null; published_on?: string | null; metadata_revision: number; document_version: number };
}) {
  const c = useDocumentCopy();
  const dialog = useRef<HTMLDialogElement>(null);
  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [page, setPage] = useState(initialPage);
  const [content, setContent] = useState<Page | null>(null);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [view, setView] = useState<"page" | "text" | "history">("page");
  const [error, setError] = useState("");
  const [contentError, setContentError] = useState("");
  const [imageError, setImageError] = useState(false);
  const [revision, setRevision] = useState(0);
  const [editing, setEditing] = useState<{ metadata: Metadata; base: number } | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const element = dialog.current; element?.showModal();
    return () => { if (element?.open) element.close(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    setError("");
    const load = async () => {
      try {
        const result = await researchRequest<DocumentDetail>(`documents/${id}`, "GET", undefined, controller.signal);
        if (controller.signal.aborted) return;
        setDocument(result); setError("");
        if (["queued", "processing"].includes(result.status)) timer = setTimeout(load, 3000);
      } catch (err) { if (!controller.signal.aborted) setError(errorText(err, c)); }
    };
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [id, revision, c]);
  useEffect(() => {
    const controller = new AbortController(); setContent(null); setContentError(""); setImageError(false);
    if (view === "history") {
      void researchRequest<{ revisions: Revision[] }>(`documents/${id}/history`, "GET", undefined, controller.signal)
        .then(result => { if (!controller.signal.aborted) setRevisions(result.revisions); })
        .catch(err => { if (!controller.signal.aborted) setContentError(errorText(err, c)); });
    } else {
      void researchRequest<Page>(`documents/${id}/pages/${page}`, "GET", undefined, controller.signal)
        .then(result => { if (!controller.signal.aborted) setContent(result); })
        .catch(err => { if (!controller.signal.aborted) setContentError(errorText(err, c)); });
    }
    return () => controller.abort();
  }, [id, page, view, revision, c]);
  async function action(path: string) {
    setBusy(true); setError("");
    try { await researchRequest(`documents/${id}/${path}`, "POST", {}); setRevision(value => value + 1); onChanged(); }
    catch (err) { setError(errorText(err, c)); }
    finally { setBusy(false); }
  }
  async function save(event: React.FormEvent) {
    event.preventDefault(); if (!editing) return;
    setBusy(true); setError("");
    try {
      await researchRequest(`documents/${id}`, "PUT", { ...metadataPayload(editing.metadata), expected_revision: editing.base, reason });
      setEditing(null); setNotice(c("Metadata revision saved. Existing report citations keep their original snapshot.", "资料信息修订已保存，已有报告引用保留原快照。"));
      setRevision(value => value + 1); onChanged();
    } catch (err) { setError(errorText(err, c)); }
    finally { setBusy(false); }
  }
  const latest = document && Math.max(...document.versions.map(item => item.version));
  return <dialog ref={dialog} className="document-dialog" aria-label={c("Document details and original pages", "资料详情与原始页面")} onCancel={onClose}>
    <div className="document-dialog-heading"><div><small>{c("RESEARCH MATERIAL", "研究资料")}</small><h2>{document?.title || c("Opening document…", "正在打开资料…")}</h2></div>
      <button className="chat-config-toggle" onClick={onClose} aria-label={c("Close document", "关闭资料")}><X size={18} /></button></div>
    {error && <div className="error-banner" role="alert">{error}<button type="button" className="chat-config-toggle" onClick={() => setRevision(value => value + 1)}>{c("Reload", "重新加载")}</button></div>}
    {document ? <div className="document-dialog-body">
      <section className="document-reader" aria-label={c("Original document", "原始资料")}>
        {citation && <details className="knowledge-citation-snapshot"><summary>{c("Stored citation snapshot", "已保存引用快照")} · v{citation.document_version} · {c("Metadata revision", "信息修订")} {citation.metadata_revision}</summary><small>{citation.published_at || citation.published_on || c("Publication unknown", "公开日期未知")}</small><blockquote>{citation.quote}</blockquote><p>{c("This snapshot records the evidence used then. The inspector shows current document metadata; later edits do not rewrite this citation.", "此快照记录当时使用的证据，右侧显示当前资料信息；后续修订不会改写引用。")}</p></details>}
        <div className="document-reader-toolbar">
          <div className="workbench-actions"><button className="chat-config-toggle" aria-pressed={view === "page"} onClick={() => setView("page")}>{c("Original page", "原始页面")}</button>
            <button className="chat-config-toggle" aria-pressed={view === "text"} onClick={() => setView("text")}>{c("Extracted text", "提取文字")}</button>
            <button className="chat-config-toggle" aria-pressed={view === "history"} onClick={() => setView("history")}>{c("Revision history", "修订历史")}</button></div>
          {view !== "history" && <div className="document-page-controls">
            <button className="chat-config-toggle" disabled={page <= 1} onClick={() => setPage(value => value - 1)} aria-label={c("Previous page", "上一页")}><ChevronLeft size={16} /></button>
            <label>{c("PDF page", "PDF 页码")}<select aria-label={c("Choose page", "选择页码")} value={page} onChange={event => setPage(Number(event.target.value))}>
              {Array.from({ length: document.page_count }, (_, index) => <option key={index + 1}>{index + 1}</option>)}
            </select></label><span>/ {document.page_count}</span>
            <button className="chat-config-toggle" disabled={page >= document.page_count} onClick={() => setPage(value => value + 1)} aria-label={c("Next page", "下一页")}><ChevronRight size={16} /></button>
          </div>}
        </div>
        {contentError && <p role="alert">{contentError}</p>}
        {view === "history" ? <ol className="document-revision-list">{revisions.map(item => <li key={item.revision}><strong>{c("Revision", "修订")} {item.revision}</strong><time>{new Date(item.created_at).toLocaleString()}</time><p>{item.reason}</p><details><summary>{c("Saved metadata", "当时资料信息")}</summary><pre>{JSON.stringify(item.metadata, null, 2)}</pre></details></li>)}</ol>
          : view === "page" ? imageError ? <div className="document-preview-empty" role="alert"><p>{c("The original page is unavailable. Check storage or reload after recovery.", "原始页面暂不可用，请检查存储或在恢复后重新加载。")}</p><button className="chat-config-toggle" onClick={() => setRevision(value => value + 1)}><RefreshCw size={14} />{c("Retry preview", "重试预览")}</button></div>
            : <img className="document-page-image" key={`${id}-${page}-${revision}`} src={`/api/research/documents/${id}/preview/${page}?r=${revision}`} alt={c(`Original PDF page ${page}`, `PDF 原始第 ${page} 页`)} onError={() => setImageError(true)} />
          : content ? <div className="document-extracted"><span className="status-badge">{statusLabel(content.status, c)}</span>
            {content.status === "needs_vision" && <p>{c("This page needs visual recognition. Empty extraction is not evidence that the original has no information.", "本页需要视觉识别。文字提取为空不代表原页没有信息。")}</p>}
            {content.error_type && <p role="alert">{content.error_type}</p>}<pre>{content.text || c("No readable text is available yet.", "暂时没有可读文字。")}</pre></div> : <p role="status">{c("Reading page…", "正在读取页面…")}</p>}
      </section>
      <aside className="document-inspector">
        <span className={`status-badge ${document.status}`}>{statusLabel(document.status, c)}</span>{document.archived && <span className="status-badge">{c("Archived", "已归档")}</span>}
        <dl><dt>{c("Version", "版本")}</dt><dd>v{document.version} · {c("Metadata revision", "信息修订")} {document.metadata_revision}</dd>
          <dt>{c("Company / issuer", "公司 / 发布机构")}</dt><dd>{document.issuer || "—"} {document.symbols.join(", ")}</dd>
          <dt>{c("Public release", "公开时间")}</dt><dd>{document.published_at || document.published_on || c("Unknown · excluded from strict historical research", "未知 · 严格历史研究中排除")}</dd>
          <dt>{c("Verification basis", "核实依据")}</dt><dd>{document.publication_basis || "—"}</dd>
          <dt>{c("Uploaded", "上传时间")}</dt><dd>{new Date(document.created_at).toLocaleString()}</dd>
          <dt>{c("Coverage", "处理覆盖")}</dt><dd>{Object.entries(document.page_states).map(([state, count]) => <div key={state}>{statusLabel(state, c)}: {count}</div>)}</dd>
          <dt>{c("Original", "原文")}</dt><dd>{document.filename} · {sizeLabel(document.byte_size)}</dd>
          <dt>{c("Citations retained", "已保留引用")}</dt><dd>{document.reference_count}</dd></dl>
        <p className="muted">{c("Text extraction is shown separately from semantic indexing and visual verification.", "文字提取、语义索引与视觉核验分别记录，不将其混为已完成的能力。")}</p>
        <div className="workbench-actions">
          <a className="chat-config-toggle" href={`/api/research/documents/${id}/download`}><Download size={14} />{c("Download", "下载原文")}</a>
          {document.source_url && <a className="chat-config-toggle" href={document.source_url} target="_blank" rel="noreferrer"><ExternalLink size={14} />{c("Source", "原始来源")}</a>}
          {!readOnly && document.latest_job_id && <button className="chat-config-toggle" onClick={() => onTask(document.latest_job_id!)}>{c("Processing task", "处理任务")}</button>}
          {!readOnly && <button className="chat-config-toggle" disabled={busy} onClick={() => void action(document.archived ? "restore" : "archive")}><Archive size={14} />{document.archived ? c("Restore", "恢复归档") : c("Archive", "归档")}</button>}
          {!readOnly && !document.archived && (["failed", "cancelled"].includes(document.status) || document.status === "partial" && document.page_states.failed > 0) && <button className="chat-config-toggle" disabled={busy} onClick={() => void action("retry")}><RefreshCw size={14} />{c("Retry text processing", "重试文字处理")}</button>}
          {!readOnly && !document.archived && document.version === latest && <button className="chat-config-toggle" onClick={() => onVersion(document)}><FilePlus2 size={14} />{c("New file version", "资料新版本")}</button>}
        </div>
        <small className="muted">{c("Archiving excludes this material from new research; the original and historical citations remain.", "归档后不再用于新研究，原文与历史引用会保留。")}</small>
        {notice && <p role="status">{notice}</p>}
        {!readOnly && (editing ? <form className="document-edit-form" onSubmit={save}><MetadataFields value={editing.metadata} onChange={value => setEditing({ ...editing, metadata: value })} />
          <label>{c("Reason for revision", "修订原因")}<input required value={reason} maxLength={1000} onChange={event => setReason(event.target.value)} /></label>
          <div className="workbench-actions"><button className="primary-button" disabled={busy}>{c("Save revision", "保存修订")}</button><button type="button" className="chat-config-toggle" disabled={busy} onClick={() => setEditing(null)}>{c("Cancel", "取消")}</button></div>
        </form> : <button className="chat-config-toggle" onClick={() => { setReason(""); setEditing({ metadata: metadataFrom(document), base: document.metadata_revision }); }}>{c("Edit metadata", "编辑资料信息")}</button>)}
        {!readOnly && document.versions.length > 1 && <label>{c("File version history", "文件版本历史")}<select value={id} onChange={event => onSwitch(event.target.value)}>{document.versions.map(item => <option key={item.id} value={item.id}>v{item.version} · {item.title}{item.archived ? " · archived" : ""}</option>)}</select></label>}
      </aside>
    </div> : !error && <p role="status"><LoaderCircle className="spin" size={16} />{c("Loading document…", "正在加载资料…")}</p>}
  </dialog>;
}
