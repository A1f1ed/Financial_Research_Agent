"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { DocumentDialog } from "@/components/documents/detail";
import { researchRequest } from "@/components/workbench-panels";
import { useDocumentCopy } from "@/components/documents/shared";
import type { CitationSelection } from "./chat-scope";

type Hit = { citation_id: string; document_id: string; page_number: number; document_version: number; quote: string;
  published_at?: string | null; published_on?: string | null; metadata_revision: number };

export function KnowledgeCitationViewer({ selection, onClose }: { selection: CitationSelection; onClose: () => void }) {
  const c = useDocumentCopy(); const dialog = useRef<HTMLDialogElement>(null); const [hit, setHit] = useState<Hit | null>(null); const [error, setError] = useState(""); const [revision, setRevision] = useState(0);
  useEffect(() => { const element = dialog.current; if (!hit) element?.showModal(); return () => { if (element?.open) element.close(); }; }, [hit]);
  useEffect(() => { const controller = new AbortController(); setHit(null); setError("");
    if (!/^[a-f0-9-]{36}$/.test(selection.searchId) || !/^K[1-9][0-9]*$/.test(selection.citationId)) { setError(c("Invalid evidence reference", "无效证据引用")); return; }
    void researchRequest<{ hits: Hit[] }>(`knowledge/searches/${selection.searchId}`, "GET", undefined, controller.signal).then(value => {
      if (controller.signal.aborted) return; const found = value.hits.find(item => item.citation_id === selection.citationId);
      if (!found) setError(c("This reference is absent from the saved search.", "已保存检索中不存在此引用。")); else setHit(found);
    }).catch(err => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : String(err)); });
    return () => controller.abort();
  }, [selection.searchId, selection.citationId, revision, c]);
  if (hit) return <DocumentDialog key={`${hit.document_id}:${hit.page_number}`} id={hit.document_id} initialPage={hit.page_number} readOnly citation={hit}
    onClose={onClose} onChanged={() => {}} onVersion={() => {}} onSwitch={() => {}} onTask={() => {}} />;
  return <dialog ref={dialog} className="document-confirm-dialog" aria-label={c("Opening cited evidence", "打开引用证据")} onCancel={onClose}><div className="workbench-item-head"><h2>{c("Source evidence", "来源证据")}</h2><button className="chat-config-toggle" onClick={onClose} aria-label={c("Close evidence", "关闭证据")}><X size={17} /></button></div>{error ? <p role="alert" className="error-banner">{error}<button className="chat-config-toggle" onClick={() => setRevision(value => value+1)}>{c("Retry", "重试")}</button></p> : <p role="status">{c("Opening the saved citation…", "正在读取已保存的引用…")}</p>}</dialog>;
}

export function StandaloneKnowledgeEvidence({ searchId, citationId }: CitationSelection) {
  const c = useDocumentCopy(); const [open, setOpen] = useState(true);
  return <main className="finance-shell knowledge-evidence-page"><div className="workbench-page"><a className="chat-config-toggle" href="/">{c("Return to research workspace", "返回研究工作台")}</a><h1>{c("Research evidence", "研究证据")}</h1><p>{c("Read the exact document version and retained citation snapshot.", "查看引用绑定的具体文档版本及保留快照。")}</p>{!open && <button className="primary-button" onClick={() => setOpen(true)}>{c("Open evidence", "打开证据")}</button>}{open && <KnowledgeCitationViewer selection={{searchId,citationId}} onClose={() => setOpen(false)} />}</div></main>;
}
