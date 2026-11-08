"use client";

import { useEffect, useState } from "react";
import { Archive, ArrowLeft, BookOpen, FileText, FolderOpen, History, Plus, RefreshCw, Settings2 } from "lucide-react";
import { DocumentLibrary } from "@/components/documents/library";
import { useDocumentCopy } from "@/components/documents/shared";
import { CollectionArchive, CollectionEditor, CollectionHistory, MemberPicker } from "./dialogs";
import { CollectionScope } from "./scope";
import { CollectionSearch } from "./search";
import { useKnowledgeResource, type Collection } from "./shared";

export function KnowledgeWorkspace({ selectedId, onSelect, onAllDocuments, onTask, onDocumentChat }: { selectedId: string | null; onSelect: (id: string | null) => void; onAllDocuments: () => void; onTask: (id: string) => void; onDocumentChat?: (collectionId: string) => void }) {
  const c = useDocumentCopy(); const [revision, setRevision] = useState(0); const [search, setSearch] = useState(""); const [query, setQuery] = useState("");
  const [archived, setArchived] = useState(false); const [page, setPage] = useState(1); const [editor, setEditor] = useState<{ initial?: Collection } | null>(null);
  const [archiving, setArchiving] = useState<Collection | null>(null); const [picker, setPicker] = useState<Collection | null>(null); const [history, setHistory] = useState<string | null>(null);
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [documentPage, setDocumentPage] = useState(1);
  const openDocument = (id: string | null, page = 1) => { setDocumentPage(page); setDocumentId(id); };
  useEffect(() => { const timer = setTimeout(() => { setQuery(search); setPage(1); }, 250); return () => clearTimeout(timer); }, [search]);
  const parameters = new URLSearchParams({ q: query, archived: String(archived), page: String(page), page_size: "20" });
  const list = useKnowledgeResource<{ collections: Collection[]; total: number }>(selectedId ? null : `knowledge/collections?${parameters}`, revision);
  const detail = useKnowledgeResource<Collection>(selectedId ? `knowledge/collections/${selectedId}` : null, revision);
  const collection = selectedId ? detail.data : null;
  const refresh = () => setRevision(value => value+1);
  const dialogs = <>{editor && <CollectionEditor initial={editor.initial} onClose={() => setEditor(null)} onSaved={id => { setEditor(null); onSelect(id); refresh(); }} />}
    {archiving && <CollectionArchive collection={archiving} onClose={() => setArchiving(null)} onSaved={() => { setArchiving(null); refresh(); }} />}
    {picker && <MemberPicker collection={picker} onClose={() => setPicker(null)} onSaved={() => { setPicker(null); refresh(); }} />}
    {history && <CollectionHistory id={history} onClose={() => setHistory(null)} />}</>;
  if (selectedId) return <div className="workbench-page knowledge-workspace">
    <button className="chat-config-toggle" onClick={() => { onSelect(null); setDocumentId(null); }}><ArrowLeft size={14} />{c("Knowledge base", "知识库")}</button>
    {detail.error && <div role="alert" className="error-banner">{detail.error}<button className="chat-config-toggle" onClick={refresh}>{c("Retry", "重试")}</button></div>}
    {!collection ? <p role="status">{detail.loading ? c("Opening collection…", "正在打开集合…") : c("Collection unavailable.", "集合不可用。")}</p> : <>
      <div className="workbench-title knowledge-heading"><div><span className="section-eyebrow">{c("KNOWLEDGE COLLECTION", "知识集合")}</span><h1><FolderOpen size={26} /> {collection.name}</h1><p className="intro">{collection.description || c("A versioned scope for company and topic research.", "按公司或主题组织、具有版本记录的研究范围。")}</p><small className="muted">{collection.symbols.join(" · ")}{collection.symbols.length && collection.topics.length ? " · " : ""}{collection.topics.join(" · ")} · {c("Revision", "修订")} {collection.revision}</small></div>
        <div className="workbench-actions"><button className="chat-config-toggle" disabled={collection.archived} onClick={() => setEditor({ initial: collection })}><Settings2 size={14} />{c("Edit collection", "编辑集合")}</button><button className="chat-config-toggle" onClick={() => setHistory(collection.id)}><History size={14} />{c("History", "历史")}</button><button className="chat-config-toggle" onClick={() => setArchiving(collection)}><Archive size={14} />{collection.archived ? c("Restore", "恢复归档") : c("Archive", "归档")}</button><button className="chat-config-toggle" onClick={refresh} aria-label={c("Refresh collection", "刷新集合")}><RefreshCw size={14} /></button></div>
      </div>
      {collection.archived && <p className="coverage-warning">{c("This collection is archived and excluded from new research. Restore it to change membership or use its scope.", "此集合已归档，不用于新研究。恢复后才可变更成员或使用范围。")}</p>}
      {onDocumentChat && <div className="workbench-actions knowledge-chat-launch"><button className="primary-button" disabled={collection.archived || !collection.coverage.active_documents} onClick={() => onDocumentChat(collection.id)}><BookOpen size={15} />{c("Ask about these documents", "就这些资料提问")}</button><small className="muted">{c("Creates a separate native chat with fixed document versions and your chosen cutoff.", "新建原生聊天会话，固定文档版本并由你选择截止日期。")}</small></div>}
      <div className="knowledge-coverage" aria-label={c("Actual collection coverage", "集合实际覆盖")}>
        <div><strong>{collection.coverage.documents}</strong><span>{c("Document versions", "文档版本")}</span><small>{collection.coverage.active_documents} {c("active", "项当前可用")}</small></div>
        <div><strong>{collection.coverage.text_pages} / {collection.coverage.pages}</strong><span>{c("Text-readable pages", "文字可读页")}</span><small>{collection.coverage.pending_pages} {c("pending", "页待处理")}</small></div>
        <div><strong>{collection.coverage.needs_vision_pages}</strong><span>{c("Pages needing vision", "待视觉页")}</span><small>{collection.coverage.failed_pages} {c("failed pages", "页失败")}</small></div>
        <div><strong>{collection.coverage.references}</strong><span>{c("Citation links retained", "保留的引用")}</span><small>{collection.coverage.archived_documents} {c("archived versions", "个已归档版本")}</small></div>
      </div>
      <p className="muted knowledge-coverage-note">{c("These counts describe extraction. Check index coverage below; unreadable pages are not included in text retrieval. Dates and source evidence are checked separately.", "以上为提取覆盖，请在下方另查索引状态；非文字可读页不会进入文字检索，日期与来源证据仍需核对。")}</p>
      <CollectionScope key={`scope:${collection.id}`} collection={collection} onDocument={openDocument} />
      <CollectionSearch key={`search:${collection.id}`} collection={collection} onDocument={openDocument} onTask={onTask} />
      <DocumentLibrary key={`documents:${collection.id}`} collection={collection} selectedId={documentId} selectedPage={documentPage} onSelect={openDocument} onTask={onTask} onCollectionChanged={refresh} onAddExisting={() => setPicker(collection)} />
    </>}{dialogs}
  </div>;
  return <div className="workbench-page knowledge-workspace">
    <div className="workbench-title"><div><span className="section-eyebrow">{c("RESEARCH KNOWLEDGE", "研究知识")}</span><h1><BookOpen size={28} /> {c("Knowledge base", "知识库")}</h1><p className="intro">{c("Organize original material by company or topic, control exact file versions and check evidence coverage.", "按公司或主题组织原始材料，管理具体文件版本并检查证据覆盖。")}</p></div><div className="workbench-actions"><button className="chat-config-toggle" onClick={onAllDocuments}><FileText size={14} />{c("All documents", "全部资料")}</button><button className="primary-button" onClick={() => setEditor({})}><Plus size={15} />{c("New collection", "新建集合")}</button></div></div>
    <div className="document-filter-bar"><label>{c("Search collections", "搜索集合")}<input value={search} onChange={event => setSearch(event.target.value)} placeholder={c("Collection name or description", "集合名称或说明")} /></label><select aria-label={c("Collection archive view", "集合归档视图")} value={String(archived)} onChange={event => { setArchived(event.target.value === "true"); setPage(1); }}><option value="false">{c("Active collections", "当前集合")}</option><option value="true">{c("Archived collections", "已归档集合")}</option></select><button className="chat-config-toggle" onClick={refresh} aria-label={c("Refresh collections", "刷新集合列表")}><RefreshCw size={15} /></button></div>
    {list.error && <div role="alert" className="error-banner">{list.error}<button className="chat-config-toggle" onClick={refresh}>{c("Retry", "重试")}</button></div>}
    {list.loading && !list.data && <p role="status">{c("Loading collections…", "正在加载集合…")}</p>}
    <div className="knowledge-grid" aria-busy={list.loading}>{list.data?.collections.map(item => <article className="finance-card knowledge-collection-card" key={item.id}>
      <FolderOpen size={22} /><button className="document-title-button" onClick={() => { onSelect(item.id); setDocumentId(null); }}>{item.name}</button><p>{item.description || c("No description", "暂无说明")}</p><small>{[...item.symbols,...item.topics].join(" · ") || c("Company or topic collection", "公司或主题资料集合")}</small>
      <div className="knowledge-card-counts"><span>{item.coverage.documents} {c("versions", "个版本")}</span><span>{item.coverage.text_pages} {c("text pages", "页可读文字")}</span><span>{item.coverage.needs_vision_pages} {c("need vision", "页待视觉")}</span></div><div className="workbench-actions"><small>{c("Revision", "修订")} {item.revision}</small><button className="chat-config-toggle" onClick={() => onSelect(item.id)}>{c("Open collection", "打开集合")}</button></div>
    </article>)}</div>
    {!list.loading && !list.error && !list.data?.collections.length && <div className="finance-card document-empty"><BookOpen size={32} /><h2>{query ? c("No matching collections", "没有匹配的集合") : archived ? c("No archived collections", "没有已归档集合") : c("Build your research library", "建立你的研究资料库")}</h2><p>{c("Create a collection, then upload new material or reuse originals already in All documents. Membership and revision history are saved by the server.", "创建集合后，可上传新材料或复用全部资料中的原文，成员范围和修订历史由服务器保存。")}</p>{!archived && <button className="primary-button" onClick={() => setEditor({})}>{c("New collection", "新建集合")}</button>}</div>}
    <div className="document-pagination"><span>{list.data?.total || 0} {c("collections", "个集合")} · {c("Page", "第")} {page}</span><div className="workbench-actions"><button className="chat-config-toggle" disabled={page <= 1 || list.loading} onClick={() => setPage(value => value-1)}>{c("Previous", "上一页")}</button><button className="chat-config-toggle" disabled={list.loading || page*20 >= (list.data?.total || 0)} onClick={() => setPage(value => value+1)}>{c("Next", "下一页")}</button></div></div>{dialogs}
  </div>;
}
