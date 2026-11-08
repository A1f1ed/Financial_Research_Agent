"use client";
import {useState} from "react";
import {useKnowledgeResource} from "@/components/knowledge/shared";
import {useDocumentCopy,errorText} from "@/components/documents/shared";
import {researchRequest} from "@/components/workbench-panels";
import {EvalDialog} from "./shared";
import type {SourceContract} from "./import-contract";
type Original={id:string;title:string;version:number;page_count:number;issuer:string;published_on:string|null;published_at:string|null};
export function ImportDialog({payload,onClose,onImported}:{payload:SourceContract;onClose:()=>void;onImported:(id:string)=>void}){
  const c=useDocumentCopy();const [chosen,setChosen]=useState<Record<string,Original>>({});const [name,setName]=useState(`Imported contract ${payload.version}`);
  const [confirmed,setConfirmed]=useState(false);const [error,setError]=useState("");const [busy,setBusy]=useState(false);const [query,setQuery]=useState("");const [page,setPage]=useState(1);const [revision,refresh]=useState(0);
  const docs=useKnowledgeResource<{documents:Original[];total:number}>(`documents?page=${page}&page_size=20&q=${encodeURIComponent(query)}`,revision,0);
  const labels=Array.from(new Set(payload.cases.flatMap(x=>Object.keys(x.evidence))));
  const originals=Array.from(new Map([...Object.values(chosen),...(docs.data?.documents||[])].map(x=>[x.id,x])).values());
  const complete=labels.every(label=>chosen[label]&&payload.cases.every(x=>(x.evidence[label]||[]).every(page=>page<=chosen[label].page_count)));
  return <EvalDialog title={c("Map source contract originals","绑定评测契约原文")} onClose={()=>!busy&&onClose()}><form onSubmit={async e=>{
    e.preventDefault();if(busy||!complete||!confirmed)return;setBusy(true);setError("");
    try{const result=await researchRequest<{id:string}>("evaluations/datasets/import","POST",{payload,name,source_documents:Object.fromEntries(Object.entries(chosen).map(([label,doc])=>[label,doc.id]))});onImported(result.id);}
    catch(err){setError(errorText(err,c));setBusy(false);}
  }}><fieldset disabled={busy}><label>{c("Dataset name","评测集名称")}<input required maxLength={120} value={name} onChange={e=>setName(e.target.value)}/></label>
    <p>{payload.cases.length} {c("cases. Bind every label to a verified uploaded original. Development/acceptance partitions are preserved.","个案例。请将每个标识绑定到已核对的上传原文，开发/验收分区会保留。")}</p>
    <label>{c("Find uploaded originals","查找已上传原文")}<input value={query} maxLength={200} onChange={e=>{setQuery(e.target.value);setPage(1);}}/></label>
    {docs.loading&&<p role="status">{c("Loading original versions…","正在读取原文版本…")}</p>}
    {docs.error&&<p role="alert">{docs.error} <button className="chat-config-toggle" type="button" onClick={()=>refresh(x=>x+1)}>{c("Retry source list","重试读取原文")}</button></p>}
    {!docs.loading&&!docs.error&&!docs.data?.documents.length&&<p>{c("No originals match this search. Existing selections are kept.","没有匹配原文，已选版本会保留。")}</p>}
    <div className="document-actions"><button className="chat-config-toggle" type="button" disabled={page===1||docs.loading} onClick={()=>setPage(x=>x-1)}>{c("Previous sources","上一页原文")}</button><span>{c("Source page","原文列表页")} {page}</span><button className="chat-config-toggle" type="button" disabled={docs.loading||page*20>=(docs.data?.total||0)} onClick={()=>setPage(x=>x+1)}>{c("Next sources","下一页原文")}</button></div>
    {labels.map(label=>{const doc=chosen[label];const pages=Array.from(new Set(payload.cases.flatMap(x=>x.evidence[label]||[]))).sort((a,b)=>a-b);return <section key={label}><label>{label}<select required value={doc?.id||""} onChange={e=>{const next=originals.find(x=>x.id===e.target.value);setChosen(previous=>{const updated={...previous};if(next)updated[label]=next;else delete updated[label];return updated;});setConfirmed(false);setError("");}}><option value="">{c("Select verified original","选择已核对原文")}</option>{originals.map(x=><option key={x.id} value={x.id}>{x.title} · v{x.version}</option>)}</select></label>{doc&&pages.some(page=>page>doc.page_count)&&<p role="alert">{c("A referenced page is outside this original. Choose the correct file version.","涉及的页码超出此原文，请选择正确文件版本。")}</p>}<p className="field-note">{c("Referenced PDF pages","涉及 PDF 页")}: {pages.join(", ")||c("None specified","未指定")}{doc&&<> · {doc.page_count} {c("total pages","页原文")} · {doc.issuer||"—"} · {c("Published","公开日期")}: {doc.published_at||doc.published_on||c("Unknown","未知")}</>}</p></section>;})}
    <p className="field-note">{c("Original references remain available for human review. Complex numeric, vision, Wiki and relation rules are not silently scored. Adapt supported checks in the draft. Import creates no published version or run.","原标准保留供人工检查，复杂数值、视觉、Wiki 与关系规则不会被静默评分。请在草稿中调整可支持规则。导入不会发布版本或启动运行。")}</p>
    <label className="evaluation-check"><input required type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>{c("I verified these source identities; import as a draft, without publishing or running.","我已核对这些来源身份；仅导入草稿，不发布、不运行。")}</label>
    {error&&<p role="alert">{error}</p>}<div className="document-actions"><button className="chat-config-toggle" type="button" onClick={onClose}>{c("Cancel","取消")}</button><button className="primary-button" disabled={busy||!confirmed||!complete} type="submit">{c("Import draft","导入草稿")}</button></div>
  </fieldset></form></EvalDialog>;
}
