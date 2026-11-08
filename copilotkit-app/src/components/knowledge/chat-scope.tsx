"use client";

import { useEffect, useRef, useState } from "react";
import type { AbstractAgent } from "@copilotkit/react-core/v2";
import { BookOpen, FileSearch, LoaderCircle, X } from "lucide-react";
import { researchRequest } from "@/components/workbench-panels";
import { useDocumentCopy } from "@/components/documents/shared";
import { useKnowledgeResource, type Collection } from "./shared";

export type CitationSelection = { searchId: string; citationId: string };
type Source = { id: string; title: string; version: number; eligible: boolean };
type Binding = { thread_id: string; search_mode: string; scope: { as_of: string | null; as_of_at: string | null; market: string; mode: string };
  snapshot: { collections: { id: string; name: string }[]; documents: Source[]; eligible_count: number; excluded_count: number } };
type Search = { id: string; query: string; created_at: string; status?:string; hits: { citation_id: string; title: string; page_number: number; document_version: number }[]; gaps: unknown[] };
type Snapshot = { binding: Binding | null; search_count: number; searches: Search[] };

function EvidenceHistory({ snapshot, onClose, onCitation }: { snapshot: Snapshot; onClose: () => void; onCitation: (value: CitationSelection) => void }) {
  const c = useDocumentCopy(); const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { const element = dialog.current; element?.showModal(); return () => { if (element?.open) element.close(); }; }, []);
  return <dialog ref={dialog} className="document-confirm-dialog knowledge-chat-evidence-dialog" aria-label={c("Conversation evidence history", "会话证据历史")} onCancel={onClose}>
    <div className="workbench-item-head"><h2>{c("Evidence used in this conversation", "本会话已使用的证据")}</h2><button className="chat-config-toggle" onClick={onClose} aria-label={c("Close used evidence", "关闭已用证据")}><X size={16} /></button></div>
    <p className="field-note">{c("Most recent 20 retrievals, including historical snapshots. Opening evidence does not rerun a tool or model.", "显示最近 20 次检索及历史快照；打开证据不会重跑工具或模型。")}</p>
    <div className="knowledge-chat-evidence">{snapshot.searches.map(item => <article key={item.id}><strong>{item.query}</strong><small>{new Date(item.created_at).toLocaleString()}</small>{item.hits.map(hit => <button className="chat-config-toggle" key={hit.citation_id} onClick={() => { onClose(); onCitation({searchId:item.id,citationId:hit.citation_id}); }}>[{hit.citation_id}] {hit.title} · v{hit.document_version} · PDF {hit.page_number}</button>)}{!item.hits.length && <p className={item.status?"error-banner":""}>{item.status==="retrieval_failed"?c("Retrieval failed; this does not establish that the originals lack an answer.","检索失败，这不表示原文中没有答案。"):item.status==="evidence_unavailable"?c("The bound evidence scope was unavailable.","绑定的证据范围当时不可用。"):c("No matching evidence was retrieved.", "当次未检索到匹配证据。")}</p>}</article>)}
      {!snapshot.search_count ? <p>{c("Evidence appears after a real retrieval tool call.", "真实检索工具运行后将在此显示证据。")}</p> : !snapshot.searches.length && <p role="status">{c("Reading saved evidence…", "正在读取已保存证据…")}</p>}</div>
  </dialog>;
}

function CreateDocumentChat({ seedId, onClose, onCreated }: { seedId?: string | null; onClose: () => void; onCreated: (id: string) => void }) {
  const c = useDocumentCopy(); const dialog = useRef<HTMLDialogElement>(null);
  const [selected, setSelected] = useState<string[]>(seedId ? [seedId] : []); const [search, setSearch] = useState(""); const [page, setPage] = useState(1);
  const [date, setDate] = useState(() => new Date().toLocaleDateString("en-CA")); const [market, setMarket] = useState("HK"); const [mode, setMode] = useState("keyword");
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const list = useKnowledgeResource<{ collections: Collection[]; total: number }>(`knowledge/collections?${new URLSearchParams({q:search,page:String(page),page_size:"20"})}`, 0);
  const embedding = useKnowledgeResource<{ verified: boolean }>("knowledge/embedding", 0);
  useEffect(() => { const element = dialog.current; element?.showModal(); return () => { if (element?.open) element.close(); }; }, []);
  async function create(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const key = crypto.randomUUID();
      await researchRequest("knowledge/conversations", "POST", { thread_id:key, collection_ids:selected, as_of:date, market, mode:"strict", search_mode:mode });
      onCreated(key);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); setBusy(false); }
  }
  return <dialog ref={dialog} className="document-confirm-dialog knowledge-chat-create" aria-label={c("New document conversation", "新建资料问答")} onCancel={event => { if (busy) event.preventDefault(); else onClose(); }}>
    <div className="workbench-item-head"><h2><BookOpen size={18} /> {c("Chat with research documents", "基于研究资料提问")}</h2><button className="chat-config-toggle" disabled={busy} onClick={onClose} aria-label={c("Close document scope", "关闭资料范围")}><X size={16} /></button></div>
    <p>{c("This creates a separate conversation with fixed file versions and a cutoff. Change the scope by starting another conversation; existing answers and citations remain.", "将新建独立会话，固定文件版本和截止日期。更换范围请新开会话，已有答案与引用会保留。")}</p>
    <form onSubmit={create}><fieldset disabled={busy}><label>{c("Find collections", "查找资料集合")}<input value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} /></label>
      {list.error && <p role="alert" className="error-banner">{list.error}</p>}
      <div className="knowledge-chat-pick" aria-busy={list.loading}>{list.data?.collections.map(item => <label key={item.id}><input type="checkbox" checked={selected.includes(item.id)} disabled={!selected.includes(item.id) && selected.length >= 8} onChange={() => setSelected(values => values.includes(item.id) ? values.filter(id => id !== item.id) : [...values,item.id])} /><span>{item.name}<small>{item.coverage.documents} {c("versions", "个版本")} · {item.coverage.text_pages} {c("text pages", "页可读文字")}</small></span></label>)}</div>
      {!list.loading && !list.data?.total && <p>{c("No active collections. Create one in Knowledge base and add material first.", "没有可用集合，请先在知识库创建集合并添加资料。")}</p>}
      <div className="document-pagination"><span>{selected.length} {c("collections selected", "个集合已选")} · {c("Page", "页")} {page}</span><div className="workbench-actions"><button type="button" className="chat-config-toggle" disabled={page <= 1 || list.loading} onClick={() => setPage(value => value-1)}>{c("Previous", "上一页")}</button><button type="button" className="chat-config-toggle" disabled={list.loading || page*20 >= (list.data?.total || 0)} onClick={() => setPage(value => value+1)}>{c("Next", "下一页")}</button></div></div>
      <div className="form-grid"><label>{c("Information cutoff date", "信息截止日期")}<input required type="date" value={date} onChange={event => setDate(event.target.value)} /></label><label>{c("Market timezone", "市场时区")}<select value={market} onChange={event => setMarket(event.target.value)}>{["HK","US","SH","SZ","SG"].map(value => <option key={value}>{value}</option>)}</select></label>
        <label className="document-wide">{c("Retrieval mode", "检索模式")}<select value={mode} onChange={event => setMode(event.target.value)}><option value="keyword">{c("Keyword · no embedding call", "关键词 · 不调用向量模型")}</option><option value="hybrid" disabled={!embedding.data?.verified}>{c("Hybrid · keyword and semantic", "混合 · 关键词与语义")}</option></select></label></div>
      <p className="field-note">{c("Up to 50 exact versions per conversation. Unknown or future publication dates are excluded. Index coverage and factual support are checked separately; this action does not run a model.", "每个会话最多固定 50 个文档版本，排除未知或晚于截止日的公开日期；索引覆盖和事实依据另行核对。创建本身不调用模型。")}</p>
      {error && <p className="error-banner" role="alert">{error}</p>}
      <div className="workbench-actions"><button type="button" className="chat-config-toggle" disabled={busy} onClick={onClose}>{c("Cancel", "取消")}</button><button className="primary-button" disabled={busy || !selected.length}>{busy && <LoaderCircle className="spin" size={15} />}{c("Start document conversation", "新建资料会话")}</button></div>
    </fieldset></form>
  </dialog>;
}

export function KnowledgeChatScope({ threadId, agent, running, request, onCreated, onReady, onBindingChange, onCitation }: {
  threadId?: string; agent: AbstractAgent; running: boolean; request: { signal: number; collectionId: string } | null;
  onCreated: (id: string) => void; onReady: (ready: boolean) => void; onBindingChange: (thread: string | null) => void; onCitation: (value: CitationSelection) => void;
}) {
  const c = useDocumentCopy(); const [open, setOpen] = useState(false); const [evidenceOpen, setEvidenceOpen] = useState(false); const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ threadId?: string; data: Snapshot | null; error: string }>({ data:null,error:"" });
  const checkedThread = useRef<string | undefined>(undefined);
  useEffect(() => { if (request) setOpen(true); }, [request]);
  useEffect(() => { if (!threadId) { onReady(true); return; } const abort = new AbortController(); if (checkedThread.current !== threadId) onReady(false);
    void researchRequest<Snapshot>(`knowledge/conversations/${threadId}${evidenceOpen ? "?include_evidence=true" : ""}`, "GET", undefined, abort.signal)
      .then(data => { if (!abort.signal.aborted) { checkedThread.current = threadId; setState({threadId,data,error:""}); onReady(true); onBindingChange(data.binding ? threadId : null); } })
      .catch(err => { if (!abort.signal.aborted) { setState(previous => ({threadId,data:previous.threadId === threadId ? previous.data : null,error:err instanceof Error ? err.message : String(err)})); if (checkedThread.current !== threadId) onReady(false); } });
    return () => abort.abort();
  }, [threadId, revision, evidenceOpen, onReady, onBindingChange]);
  useEffect(() => { const subscription = agent.subscribe({ onRunFinishedEvent: ({ input }) => { if (input.threadId === threadId) setRevision(value => value+1); } }); return () => subscription.unsubscribe(); }, [agent, threadId]);
  const snapshot = state.threadId === threadId ? state.data : null; const binding = snapshot?.binding;
  return <div className="knowledge-chat-scope">
    <div className="workbench-actions"><button className="chat-config-toggle" disabled={running} onClick={() => setOpen(true)}><BookOpen size={14} />{c("Chat with documents", "基于资料提问")}</button>
      {binding && <><span className="knowledge-chat-bound">{binding.snapshot.collections.map(item => item.name).join(" · ")} · {binding.snapshot.documents.length} {c("versions", "个版本")} · {binding.scope.as_of || binding.scope.as_of_at} · {binding.search_mode === "hybrid" ? c("Hybrid", "混合") : c("Keyword", "关键词")}</span><button className="chat-config-toggle" aria-expanded={evidenceOpen} onClick={() => setEvidenceOpen(value => !value)}><FileSearch size={14} />{c("Evidence used", "已用证据")} ({snapshot.search_count})</button></>}
    </div>
    {!snapshot && threadId && !state.error && <small role="status">{c("Checking conversation scope…", "正在核对会话范围…")}</small>}
    {state.threadId === threadId && state.error && <p className="error-banner" role="alert">{state.error}<button className="chat-config-toggle" onClick={() => setRevision(value => value+1)}>{c("Retry", "重试")}</button></p>}
    {binding && <small>{c("Fixed document scope · citations retained · changing scope starts a new chat", "固定资料范围 · 保留引用 · 更换范围需新建会话")}</small>}
    {evidenceOpen && binding && <EvidenceHistory snapshot={snapshot} onClose={() => setEvidenceOpen(false)} onCitation={onCitation} />}
    {open && <CreateDocumentChat seedId={request?.collectionId} onClose={() => setOpen(false)} onCreated={key => { setOpen(false); setEvidenceOpen(false); onCreated(key); }} />}
  </div>;
}
