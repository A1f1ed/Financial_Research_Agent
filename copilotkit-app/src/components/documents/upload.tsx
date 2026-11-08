"use client";

import { useEffect, useRef, useState } from "react";
import { Link2, UploadCloud, X, Check, LoaderCircle } from "lucide-react";
import { researchRequest } from "@/components/workbench-panels";
import { MetadataFields, emptyMetadata, metadataPayload, errorText, sizeLabel, useDocumentCopy, type Metadata, type DocumentSummary } from "./shared";

type QueuedFile = { id: string; file: File; title: string; state: "waiting" | "uploading" | "queued" | "duplicate" | "failed" | "cancelled"; percent: number; error?: string; documentId?: string };
function uploadFile(item: QueuedFile, metadata: Metadata, previousId: string | undefined, collectionId: string | undefined, progress: (value: number) => void, capture: (xhr: XMLHttpRequest) => void) {
  return new Promise<{ document: DocumentSummary; duplicate: boolean; collection_assignment?: { status: string } | null }>((resolve, reject) => {
    const xhr = new XMLHttpRequest(); capture(xhr);
    xhr.open("POST", "/api/research/documents/upload");
    xhr.timeout = 120000;
    xhr.upload.onprogress = event => { if (event.lengthComputable) progress(Math.round(event.loaded / event.total * 100)); };
    xhr.onload = () => {
      try {
        const result = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300) resolve(result);
        else reject(new Error(typeof result.detail === "string" ? result.detail : Array.isArray(result.detail) ? result.detail[0]?.msg : result.error || "Upload failed"));
      } catch { reject(new Error("The upload response could not be read")); }
    };
    xhr.onerror = () => reject(new Error("Upload connection failed"));
    xhr.ontimeout = () => reject(new Error("Upload timed out; check the library before retrying"));
    xhr.onabort = () => reject(new Error("Upload interrupted; completed files may already appear in the library"));
    const form = new FormData();
    form.append("file", item.file);
    form.append("metadata", JSON.stringify({ ...metadataPayload(metadata, item.title), previous_version_id: previousId || null, collection_id: collectionId || null }));
    xhr.send(form);
  });
}

export function DocumentUpload({ initial, previousId, collectionId, onClose, onChanged, onOpen, onTask }: {
  initial?: Metadata; previousId?: string; collectionId?: string; onClose: () => void; onChanged: () => void; onOpen: (id: string) => void; onTask: (id: string) => void;
}) {
  const c = useDocumentCopy();
  const [mode, setMode] = useState<"files" | "url">("files");
  const [metadata, setMetadata] = useState(initial || emptyMetadata());
  const [queue, setQueue] = useState<QueuedFile[]>([]);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef<XMLHttpRequest | null>(null);
  const interrupted = useRef(false);
  useEffect(() => () => { interrupted.current = true; active.current?.abort(); }, []);
  const canUpload = (item: QueuedFile) => ["waiting", "failed", "cancelled"].includes(item.state)
    && item.file.size <= (/\.(png|jpe?g)$/i.test(item.file.name) ? 20 : 50) * 1024 * 1024;
  const update = (id: string, values: Partial<QueuedFile>) => setQueue(items => items.map(item => item.id === id ? { ...item, ...values } : item));
  const choose = (files: FileList | null) => {
    if (!files || busy) return;
    if (files.length > 10 || previousId && files.length !== 1) { setError(c("Select up to 10 files, or one file for a new version.", "每批最多选择 10 份文件；新版本只选择一份文件。")); return; }
    setError("");
    setQueue(Array.from(files).map(file => {
      const limit = /\.(png|jpe?g)$/i.test(file.name) ? 20 : 50;
      const oversized = file.size > limit * 1024 * 1024;
      return { id: crypto.randomUUID(), file, title: previousId && metadata.title ? metadata.title : file.name.replace(/\.[^.]+$/, ""),
        state: oversized ? "failed" : "waiting", percent: 0,
        ...(oversized ? { error: c(`File exceeds ${limit} MB; choose a smaller file.`, `文件超过 ${limit} MB，请重新选择较小的文件。`) } : {}) };
    }));
  };
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); interrupted.current = false;
    try {
      if (mode === "url") {
        const result = await researchRequest<{ id: string }>("documents/import", "POST", { url, metadata: { ...metadataPayload(metadata), previous_version_id: previousId || null, collection_id: collectionId || null } });
        onChanged(); onTask(result.id); return;
      }
      for (const item of queue.filter(canUpload)) {
        if (interrupted.current) break;
        update(item.id, { state: "uploading", percent: 0, error: undefined });
        try {
          const result = await uploadFile(item, metadata, previousId, collectionId, value => update(item.id, { percent: value }), xhr => { active.current = xhr; });
          update(item.id, { state: result.duplicate ? "duplicate" : "queued", percent: 100, documentId: result.document.id,
            error: result.collection_assignment?.status === "not_added" ? c("File retained, but the collection changed or is unavailable. Restore the collection and add this file from All documents.", "原文已保留，但集合已变更或不可用。请恢复集合后从全部资料中添加。") : undefined }); onChanged();
        } catch (err) { update(item.id, { state: interrupted.current ? "cancelled" : "failed", error: errorText(err, c) }); }
        finally { active.current = null; }
      }
    } catch (err) { setError(errorText(err, c)); }
    finally { setBusy(false); }
  }
  return <section className="finance-card document-upload">
    <div className="workbench-item-head"><h2>{previousId ? c("Upload a new document version", "上传资料新版本") : c("Add research material", "添加研究资料")}</h2>
      <button type="button" className="chat-config-toggle" disabled={busy} onClick={onClose} aria-label={c("Close upload form", "关闭上传表单")}><X size={16} /></button></div>
    <div className="workbench-actions" role="group" aria-label={c("Import method", "导入方式")}>
      <button type="button" className="chat-config-toggle" aria-pressed={mode === "files"} disabled={busy} onClick={() => setMode("files")}><UploadCloud size={15} />{c("Upload files", "上传文件")}</button>
      <button type="button" className="chat-config-toggle" aria-pressed={mode === "url"} disabled={busy} onClick={() => setMode("url")}><Link2 size={15} />{c("Official source link", "官方来源链接")}</button>
    </div>
    <form onSubmit={submit}>
      {mode === "files" ? <>
        <label className="document-dropzone" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); choose(event.dataTransfer.files); }}>
          <UploadCloud size={25} /><strong>{c("Choose or drop PDF, PNG or JPEG files", "选择或拖放 PDF、PNG、JPEG 文件")}</strong>
          <span>{c("PDF: 50 MB / 500 pages · Images: 20 MB / 30 MP · Up to 10 files", "PDF：50 MB / 500 页 · 图片：20 MB / 3000 万像素 · 每批最多 10 份")}</span>
          <input type="file" accept=".pdf,.png,.jpg,.jpeg" multiple={!previousId} disabled={busy} onChange={event => choose(event.target.files)} />
        </label>
        {queue.length > 0 && <ul className="document-upload-queue">{queue.map(item => <li key={item.id}>
          <div><input required maxLength={250} aria-label={c("Title for ", "文件标题：") + item.file.name} value={item.title} disabled={busy || ["queued", "duplicate"].includes(item.state)} onChange={event => update(item.id, { title: event.target.value })} /><small>{item.file.name} · {sizeLabel(item.file.size)}</small></div>
          <div className="document-upload-result">{item.state === "uploading" ? <><LoaderCircle size={15} className="spin" />{item.percent}%</> : item.documentId ? <button type="button" className="chat-config-toggle" onClick={() => onOpen(item.documentId!)}><Check size={14} />{item.state === "duplicate" ? c("Already in library", "已在资料库") : c("Open processing", "查看处理")}</button> : <small>{c(item.state, ({ waiting: "待上传", failed: "失败", cancelled: "已中止" } as Record<string, string>)[item.state] || item.state)}</small>}</div>
          {item.error && <p role="alert">{item.error}</p>}
        </li>)}</ul>}
      </> : <label>{c("Direct file URL from an official source", "官方来源文件直链")}<input required type="url" value={url} onChange={event => setUrl(event.target.value)} placeholder="https://www.hkexnews.hk/…/report.pdf" />
        <small>{c("Supported: HKEXnews, BYD Global, Geely Auto and European Commission. Redirects and public network addresses are verified by the server.", "支持港交所披露易、比亚迪官网、吉利汽车官网和欧盟委员会。服务器会核实重定向和公网地址。")}</small></label>}
      <fieldset disabled={busy}><MetadataFields value={metadata} onChange={setMetadata} showTitle={mode === "url"} /></fieldset>
      {error && <p role="alert" className="error-banner">{error}</p>}
      <div className="workbench-actions">
        {busy && mode === "files" ? <button type="button" className="chat-config-toggle" onClick={() => { interrupted.current = true; active.current?.abort(); }}>{c("Stop uploading", "停止上传")}</button>
          : <button className="primary-button" disabled={busy || mode === "files" && !queue.some(canUpload)}>{busy ? c("Submitting…", "正在提交…") : mode === "url" ? c("Start import", "开始导入") : c("Upload & process", "上传并处理")}</button>}
        <small className="muted">{c("Files are retained in your document library. Text extraction runs independently in the background.", "原文保存到资料库，文字提取在独立后台任务中进行。")}</small>
      </div>
    </form>
  </section>;
}
