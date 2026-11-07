"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { researchRequest } from "@/components/workbench-panels";
import { errorText, useDocumentCopy, type DocumentSummary } from "@/components/documents/shared";
import { useKnowledgeResource, type Collection } from "./shared";

function useModal() {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const element = ref.current; element?.showModal(); return () => element?.close(); }, []);
  return ref;
}

export function CollectionEditor({ initial, onClose, onSaved }: { initial?: Collection; onClose: () => void; onSaved: (id: string) => void }) {
  const c = useDocumentCopy(); const dialog = useModal();
  const [name, setName] = useState(initial?.name || ""); const [description, setDescription] = useState(initial?.description || "");
  const [symbols, setSymbols] = useState(initial?.symbols.join(", ") || ""); const [topics, setTopics] = useState(initial?.topics.join(", ") || "");
  const [reason, setReason] = useState(""); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    const split = (value: string) => value.split(/[,，]/).map(item => item.trim()).filter(Boolean);
    try {
      const result = await researchRequest<{ id: string }>(`knowledge/collections${initial ? `/${initial.id}` : ""}`, initial ? "PUT" : "POST",
        { name, description, symbols: split(symbols), topics: split(topics), ...(initial ? { expected_revision: initial.revision, reason } : {}) });
      onSaved(result.id);
    } catch (err) { setError(errorText(err, c)); setBusy(false); }
  }
  return <dialog ref={dialog} className="document-confirm-dialog knowledge-editor" aria-label={initial ? c("Edit collection", "编辑资料集合") : c("Create knowledge collection", "创建知识集合")} onCancel={event => { if (busy) event.preventDefault(); else onClose(); }}>
    <div className="workbench-item-head"><h2>{initial ? c("Edit collection", "编辑资料集合") : c("Create a collection", "创建资料集合")}</h2><button className="chat-config-toggle" disabled={busy} onClick={onClose} aria-label={c("Close collection editor", "关闭集合编辑")}><X size={17} /></button></div>
    <p>{c("Organize explicit document versions around a company or research topic. Creating a collection does not run a model.", "围绕公司或主题组织明确的文档版本。创建集合不会调用模型。")}</p>
    <form onSubmit={save}><fieldset disabled={busy}>
      <label>{c("Collection name", "集合名称")}<input required maxLength={120} value={name} onChange={event => setName(event.target.value)} /></label>
      <label>{c("Description", "说明")}<textarea rows={3} maxLength={2000} value={description} onChange={event => setDescription(event.target.value)} /></label>
      <label>{c("Symbols, separated by commas", "证券代码，用逗号分隔")}<input value={symbols} onChange={event => setSymbols(event.target.value)} placeholder="1211.HK, 175.HK" /></label>
      <label>{c("Topics, separated by commas", "主题，用逗号分隔")}<input value={topics} onChange={event => setTopics(event.target.value)} placeholder={c("EV policy, cash flow", "电动车政策, 现金流")} /></label>
      {initial && <label>{c("Reason for revision", "修订原因")}<input required maxLength={1000} value={reason} onChange={event => setReason(event.target.value)} /></label>}
    </fieldset>{error && <p role="alert" className="error-banner">{error}</p>}
      <div className="workbench-actions"><button type="button" className="chat-config-toggle" disabled={busy} onClick={onClose}>{c("Cancel", "取消")}</button><button className="primary-button" disabled={busy}>{busy ? c("Saving…", "正在保存…") : initial ? c("Save revision", "保存修订") : c("Create collection", "创建集合")}</button></div>
    </form>
  </dialog>;
}

export function CollectionArchive({ collection, onClose, onSaved }: { collection: Collection; onClose: () => void; onSaved: () => void }) {
  const c = useDocumentCopy(); const dialog = useModal(); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  async function apply() {
    setBusy(true); setError("");
    try { await researchRequest(`knowledge/collections/${collection.id}/${collection.archived ? "restore" : "archive"}`, "POST", { expected_revision: collection.revision }); onSaved(); }
    catch (err) { setError(errorText(err, c)); setBusy(false); }
  }
  return <dialog ref={dialog} className="document-confirm-dialog" aria-label={c("Confirm collection availability", "确认集合可用性操作")} onCancel={event => { if (busy) event.preventDefault(); else onClose(); }}>
    <h2>{collection.archived ? c("Restore this collection?", "恢复此资料集合？") : c("Archive this collection?", "归档此资料集合？")}</h2>
    <p><strong>{collection.name}</strong></p><p>{collection.coverage.documents} {c("document versions", "个文档版本")} · {collection.coverage.references} {c("citation links retained", "条引用保留")}</p>
    <p>{collection.archived ? c("Its document membership will be restored. Publication dates and document availability are still checked for each research run. No model or processing task starts automatically.", "恢复集合成员范围。研究仍需检查公开日期及资料可用性，不会自动启动模型或处理任务。")
      : c("New research cannot use this collection. Originals, other collections, shared processing tasks and historical citations are retained.", "新研究不能再使用此集合。原文、其他集合、共享处理任务和历史引用均保留。")}</p>
    {error && <p role="alert" className="error-banner">{error}</p>}<div className="workbench-actions"><button className="chat-config-toggle" disabled={busy} onClick={onClose}>{c("Cancel", "取消")}</button><button className="primary-button" disabled={busy} onClick={() => void apply()}>{busy ? c("Applying…", "正在处理…") : collection.archived ? c("Restore collection", "恢复集合") : c("Archive collection", "归档集合")}</button></div>
  </dialog>;
}

export function MemberPicker({ collection, onClose, onSaved }: { collection: Collection; onClose: () => void; onSaved: () => void }) {
  const c = useDocumentCopy(); const dialog = useModal(); const [search, setSearch] = useState(""); const [query, setQuery] = useState(""); const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string[]>([]); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  useEffect(() => { const timer = setTimeout(() => { setQuery(search); setPage(1); }, 250); return () => clearTimeout(timer); }, [search]);
  useEffect(() => { setSelected([]); }, [query, page]);
  const parameters = new URLSearchParams({ collection_id: collection.id, outside_collection: "true", q: query, page: String(page), page_size: "20" });
  const result = useKnowledgeResource<{ documents: DocumentSummary[]; total: number }>(`documents?${parameters}`, 0);
  const ready = !result.loading && search === query && !busy;
  const items = result.data?.documents || [];
  async function add() {
    setBusy(true); setError("");
    try { await researchRequest(`knowledge/collections/${collection.id}/members`, "POST", { action: "add", document_ids: selected, expected_revision: collection.revision }); onSaved(); }
    catch (err) { setError(errorText(err, c)); setBusy(false); }
  }
  return <dialog ref={dialog} className="document-confirm-dialog knowledge-picker" aria-label={c("Add existing document versions", "添加已有文档版本")} onCancel={event => { if (busy) event.preventDefault(); else onClose(); }}>
    <div className="workbench-item-head"><h2>{c("Add existing material", "添加已有资料")}</h2><button className="chat-config-toggle" disabled={busy} onClick={onClose} aria-label={c("Close document picker", "关闭资料选择")}><X size={17} /></button></div>
    <p>{c("Choose exact file versions for ", "选择加入以下集合的具体文件版本：")}{collection.name}{c(". Originals and existing processing are reused.", "。复用原文和已有处理，不重复调用模型。")}</p>
    <label>{c("Search available material", "搜索可添加资料")}<input value={search} disabled={busy} onChange={event => setSearch(event.target.value)} placeholder={c("Title or issuer", "标题或发布机构")} /></label>
    {result.loading && <p role="status">{c("Loading material…", "正在加载资料…")}</p>}
    {(error || result.error) && <p role="alert" className="error-banner">{error || result.error}</p>}
    <div className="knowledge-picker-list">{items.map(item => <label key={item.id}><input type="checkbox" disabled={!ready} checked={selected.includes(item.id)} onChange={event => setSelected(value => event.target.checked ? [...value, item.id] : value.filter(id => id !== item.id))} /><span><strong>{item.title}</strong><small>v{item.version} · {item.issuer || item.filename} · {item.page_count} {c("pages", "页")}</small></span></label>)}</div>
    {!result.loading && !items.length && <p>{c("No available versions match. Restore archived originals from All documents, or upload new material.", "没有可添加的匹配版本。可从全部资料恢复已归档原文，或上传新资料。")}</p>}
    <div className="document-pagination"><span>{result.data?.total || 0} {c("available versions", "个可添加版本")} · {c("Page", "第")} {page}</span><div className="workbench-actions"><button className="chat-config-toggle" disabled={busy || page <= 1} onClick={() => setPage(value => value-1)}>{c("Previous", "上一页")}</button><button className="chat-config-toggle" disabled={busy || result.loading || page*20 >= (result.data?.total || 0)} onClick={() => setPage(value => value+1)}>{c("Next", "下一页")}</button></div></div>
    <div className="workbench-actions"><button className="chat-config-toggle" disabled={busy} onClick={onClose}>{c("Cancel", "取消")}</button><button className="primary-button" disabled={!ready || !selected.length} onClick={() => void add()}>{busy ? c("Adding…", "正在添加…") : `${c("Add selected", "添加所选")} (${selected.length})`}</button></div>
  </dialog>;
}

type Revision = { revision: number; operation: string; reason: string; created_at: string; snapshot: { name: string; changes: Record<string, { id: string; version: number }[]> } };
export function CollectionHistory({ id, onClose }: { id: string; onClose: () => void }) {
  const c = useDocumentCopy(); const dialog = useModal(); const [page, setPage] = useState(1);
  const result = useKnowledgeResource<{ revisions: Revision[]; total: number }>(`knowledge/collections/${id}/history?page=${page}`, 0);
  const operations: Record<string, [string, string]> = { created: ["Created", "创建"], metadata_edited: ["Metadata revised", "信息修订"], archived: ["Archived", "归档"], restored: ["Restored", "恢复"], members_added: ["Versions added", "添加版本"], members_removed: ["Versions removed", "移出版本"], upload_added: ["Uploaded version added", "上传版本加入"] };
  return <dialog ref={dialog} className="document-confirm-dialog knowledge-history" aria-label={c("Collection audit history", "集合审计历史")} onCancel={onClose}>
    <div className="workbench-item-head"><h2>{c("Collection history", "集合历史")}</h2><button className="chat-config-toggle" onClick={onClose} aria-label={c("Close collection history", "关闭集合历史")}><X size={17} /></button></div>
    {result.error && <p role="alert">{result.error}</p>}{result.loading && <p role="status">{c("Loading history…", "正在加载历史…")}</p>}
    <ol className="document-revision-list">{result.data?.revisions.map(item => <li key={item.revision}><strong>{c("Revision", "修订")} {item.revision} · {operations[item.operation] ? c(...operations[item.operation]) : item.operation}</strong><time>{new Date(item.created_at).toLocaleString()}</time><p>{item.reason}</p><small>{item.snapshot.name}</small>{Object.entries(item.snapshot.changes).map(([action, items]) => <div key={action}>{action === "added" ? c("Added", "添加") : c("Removed", "移出")} {items.length} {c("version(s)", "个版本")}{items.map(value => <code key={value.id}>v{value.version} · {value.id.slice(0,8)}</code>)}</div>)}</li>)}</ol>
    <div className="workbench-actions"><button className="chat-config-toggle" disabled={page <= 1} onClick={() => setPage(value => value-1)}>{c("Previous", "上一页")}</button><button className="chat-config-toggle" disabled={result.loading || page*20 >= (result.data?.total || 0)} onClick={() => setPage(value => value+1)}>{c("Next", "下一页")}</button></div>
  </dialog>;
}
