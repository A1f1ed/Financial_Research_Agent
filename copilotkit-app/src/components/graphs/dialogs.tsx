"use client";
import { useEffect,useRef,useState } from "react";
import { X } from "lucide-react";
import { researchRequest } from "@/components/workbench-panels";
import { errorText,useDocumentCopy,type DocumentDetail } from "@/components/documents/shared";
import { useKnowledgeResource,type Collection } from "@/components/knowledge/shared";
import { entityKinds,relationKinds,graphLabel,type Evidence,type Entity,type Graph,type Relation } from "./shared";
import { evidenceSelection } from "@/lib/graph-evidence-selection";

export function GraphModal({title,onClose,busy=false,children}:{title:string;onClose:()=>void;busy?:boolean;children:React.ReactNode}){
  const ref=useRef<HTMLDialogElement>(null);const c=useDocumentCopy();
  useEffect(()=>{const element=ref.current;element?.showModal();return()=>element?.close();},[]);
  return <dialog ref={ref} className="document-confirm-dialog graph-modal knowledge-editor" aria-label={title} onCancel={event=>{if(busy)event.preventDefault();else onClose();}}>
    <div className="workbench-item-head"><h2>{title}</h2><button type="button" className="chat-config-toggle" disabled={busy} onClick={onClose} aria-label={c("Close dialog","关闭弹窗")}><X size={17}/></button></div>{children}</dialog>;
}

export function GraphEditor({initial,onClose,onSaved}:{initial?:Graph;onClose:()=>void;onSaved:(id:string)=>void}){
  const c=useDocumentCopy();const [name,setName]=useState(initial?.name||"");const [description,setDescription]=useState(initial?.description||"");
  const [selected,setSelected]=useState<string[]>(initial?.scope.collection_ids||[]);const [date,setDate]=useState(initial?.scope.as_of||new Date().toLocaleDateString("en-CA"));
  const [market,setMarket]=useState(initial?.scope.market||"HK");const [types,setTypes]=useState(initial?.relation_types||Object.keys(relationKinds));
  const [q,setQ]=useState("");const [page,setPage]=useState(1);const [reason,setReason]=useState("");const [busy,setBusy]=useState(false);const [error,setError]=useState("");
  const collections=useKnowledgeResource<{collections:Collection[];total:number}>(`knowledge/collections?${new URLSearchParams({q,page:String(page),page_size:"20"})}`,0);
  async function save(event:React.FormEvent){event.preventDefault();setBusy(true);setError("");try{
    const row=await researchRequest<{id:string}>(`graphs${initial?`/${initial.id}`:""}`,initial?"PUT":"POST",{name,description,relation_types:types,
      scope:{collection_ids:selected,document_ids:initial?.scope.document_ids||[],as_of:date,market,mode:"strict"},...(initial?{expected_revision:initial.revision,reason}:{})});onSaved(row.id);
  }catch(err){setError(errorText(err,c));setBusy(false);}}
  return <GraphModal title={initial?c("Edit graph scope","修订图谱范围"):c("Create a research graph","创建研究图谱")} onClose={onClose} busy={busy}>
    <p>{c("Pin exact document versions from your collections. New members require an explicit scope revision. No extraction or model run starts on creation.","固定集合中的文档版本；后续新增资料需要明确修订图谱范围。创建不会自动运行抽取或模型。")}</p>
    <form onSubmit={save}><fieldset disabled={busy}><label>{c("Graph name","图谱名称")}<input required maxLength={120} value={name} onChange={e=>setName(e.target.value)}/></label>
      <label>{c("Description","说明")}<textarea maxLength={2000} rows={2} value={description} onChange={e=>setDescription(e.target.value)}/></label>
      <div className="form-grid"><label>{c("Source cutoff","资料截止日期")}<input type="date" required value={date} onChange={e=>setDate(e.target.value)}/></label><label>{c("Market timezone","市场时区")}<select value={market} onChange={e=>setMarket(e.target.value)}>{["HK","US","SH","SZ","SG"].map(v=><option key={v}>{v}</option>)}</select></label></div>
      <label>{c("Find collections","查找集合")}<input value={q} onChange={e=>{setQ(e.target.value);setPage(1);}}/></label>
      <p className="muted">{selected.length} / 8 {c("collections selected · maximum 50 document versions","个集合已选 · 最多 50 个文档版本")}</p>
      {selected.map(id=><button key={id} type="button" className="chat-config-toggle" onClick={()=>setSelected(items=>items.filter(v=>v!==id))}>{initial?.snapshot.collections.find(v=>v.id===id)?.name||collections.data?.collections.find(v=>v.id===id)?.name||id} ×</button>)}
      {collections.error&&<p role="alert" className="error-banner">{collections.error}</p>}
      <div className="graph-collection-picker">{collections.data?.collections.map(item=><label key={item.id}><input type="checkbox" checked={selected.includes(item.id)} disabled={!selected.includes(item.id)&&selected.length>=8} onChange={e=>setSelected(items=>e.target.checked?[...items,item.id]:items.filter(v=>v!==item.id))}/><span>{item.name}<small>{item.coverage.active_documents} {c("active documents","个可用文档")}</small></span></label>)}{collections.data?.total===0&&<p>{c("Create a knowledge collection first.","请先在知识库创建集合。")}</p>}</div>
      <div className="workbench-actions"><button type="button" className="chat-config-toggle" disabled={page===1} onClick={()=>setPage(v=>v-1)}>{c("Previous","上一页")}</button><span>{page}</span><button type="button" className="chat-config-toggle" disabled={page*20>=(collections.data?.total||0)} onClick={()=>setPage(v=>v+1)}>{c("Next","下一页")}</button></div>
      <details><summary>{c("Allowed relationship types","允许的关系类型")} · {types.length}</summary><div className="graph-checkboxes">{Object.entries(relationKinds).map(([key,label])=><label key={key}><input type="checkbox" checked={types.includes(key)} onChange={e=>setTypes(items=>e.target.checked?[...items,key]:items.filter(v=>v!==key))}/>{c(label[0],label[1])}</label>)}</div></details>
      {initial&&<label>{c("Reason for revision","修订原因")}<textarea required value={reason} maxLength={1000} onChange={e=>setReason(e.target.value)}/></label>}
      {error&&<div role="alert" className="error-banner">{error}</div>}<div className="workbench-actions"><button type="button" className="chat-config-toggle" onClick={onClose}>{c("Cancel","取消")}</button><button className="primary-button" disabled={!name.trim()||!types.length||(!selected.length&&!initial?.scope.document_ids.length)||busy}>{busy?c("Saving…","保存中…"):c("Save scope","保存范围")}</button></div>
    </fieldset></form></GraphModal>;
}

export function EvidencePicker({graph,value,onChange}:{graph:Graph;value:Evidence[];onChange:(v:Evidence[])=>void}){
  const c=useDocumentCopy();const [documentId,setDocumentId]=useState("");const [page,setPage]=useState(1);const [span,setSpan]=useState<[number,number]>([0,0]);
  const doc=useKnowledgeResource<DocumentDetail>(documentId?`documents/${documentId}`:null,0);
  const content=useKnowledgeResource<{text:string;status:string}>(documentId?`documents/${documentId}/pages/${page}`:null,0);
  const selection=content.data?evidenceSelection(content.data.text,span[0],span[1]):null;
  const selectionLength=selection?selection.end_offset-selection.start_offset:0;
  const valid=selectionLength>=2&&selectionLength<=4000&&content.data?.status==="text_ready";
  return <section className="graph-evidence-picker"><h3>{c("Original-page evidence","原文页面证据")}</h3>
    {value.map((item,index)=><div className="graph-evidence-chip" key={`${item.document_id}:${index}`}><small>{graph.snapshot.documents.find(d=>d.id===item.document_id)?.title} · PDF {item.page_number}</small><blockquote>{item.quote}</blockquote><button type="button" className="chat-config-toggle danger-button" onClick={()=>onChange(value.filter((_,i)=>i!==index))}>{c("Remove evidence","移除此证据")}</button></div>)}
    <label>{c("Choose a pinned document","选择已固定的文档")}<select value={documentId} onChange={e=>{setDocumentId(e.target.value);setPage(1);setSpan([0,0]);}}><option value="">{c("Select source…","选择来源…")}</option>{graph.snapshot.documents.filter(v=>v.eligible).map(item=><option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
    {documentId&&<><div className="workbench-actions"><button type="button" className="chat-config-toggle" disabled={page<=1} onClick={()=>{setPage(v=>v-1);setSpan([0,0]);}}>{c("Previous page","上一页")}</button><span>PDF {page} / {doc.data?.page_count||"…"}</span><button type="button" className="chat-config-toggle" disabled={!doc.data||page>=doc.data.page_count} onClick={()=>{setPage(v=>v+1);setSpan([0,0]);}}>{c("Next page","下一页")}</button></div>
      {content.error&&<p role="alert" className="error-banner">{content.error}</p>}
      <label>{c("Select the exact supporting passage (2–4,000 characters)","选中支持此内容的原文段落（2–4,000 字符）")}<textarea readOnly rows={7} value={content.data?.text||""} onSelect={e=>setSpan([e.currentTarget.selectionStart,e.currentTarget.selectionEnd])}/></label>
      {content.loading&&<p role="status">{c("Loading page…","正在加载页面…")}</p>}{content.data&&content.data.status!=="text_ready"&&<p className="coverage-warning">{c("This page has no usable text evidence yet.","此页尚无可用的文字证据。")}</p>}
      {selection&&<div className="graph-evidence-chip"><small>{c("Selected passage preview","选中引文预览")}</small><blockquote>{selection.quote}</blockquote></div>}
      <button type="button" className="chat-config-toggle" disabled={!valid||value.length>=8} onClick={()=>{if(selection&&valid)onChange([...value,{document_id:documentId,page_number:page,...selection}]);setSpan([0,0]);}}>{c("Use selected passage","使用选中原文")} · {selectionLength}</button></>}
  </section>;
}

export function EntitySelector({graphId,value,onChange,label}:{graphId:string;value:string;onChange:(v:string)=>void;label:string}){
  const c=useDocumentCopy();const [q,setQ]=useState("");const [page,setPage]=useState(1);
  const list=useKnowledgeResource<{entities:Entity[];total:number}>(`graphs/${graphId}/entities?${new URLSearchParams({q,page:String(page),page_size:"20"})}`,0);
  return <div className="graph-entity-selector"><label>{label}<input aria-label={`${label} · ${c("Search","搜索")}`} value={q} onChange={e=>{setQ(e.target.value);setPage(1);}} placeholder={c("Search identities and aliases","搜索实体及别名")}/><select aria-label={label} required value={value} onChange={e=>onChange(e.target.value)}><option value="">{c("Choose an identity…","选择实体…")}</option>{value&&!list.data?.entities.some(v=>v.id===value)&&<option value={value}>{value}</option>}{list.data?.entities.map(v=><option key={v.id} value={v.id}>{v.name} · {graphLabel(v.kind,c)}</option>)}</select></label>{list.error&&<p role="alert" className="error-banner">{list.error}</p>}<div className="workbench-actions"><button type="button" className="chat-config-toggle" disabled={page===1} onClick={()=>setPage(v=>v-1)}>{c("Previous","上一页")}</button><small>{page}</small><button type="button" className="chat-config-toggle" disabled={page*20>=(list.data?.total||0)} onClick={()=>setPage(v=>v+1)}>{c("Next","下一页")}</button></div></div>;
}

export function EntityEditor({graph,initial,onClose,onSaved}:{graph:Graph;initial?:Entity;onClose:()=>void;onSaved:()=>void}){
  const c=useDocumentCopy();const [name,setName]=useState(initial?.name||"");const [kind,setKind]=useState(initial?.kind||"company");const [aliases,setAliases]=useState(initial?.aliases.join(", ")||"");const [symbols,setSymbols]=useState(initial?.symbols.join(", ")||"");
  const [evidence,setEvidence]=useState<Evidence[]>(initial?.evidence||[]);const [reason,setReason]=useState("");const [error,setError]=useState("");const [busy,setBusy]=useState(false);
  async function save(event:React.FormEvent){event.preventDefault();setBusy(true);setError("");try{
    const split=(v:string)=>v.split(/[,，]/).map(i=>i.trim()).filter(Boolean);
    await researchRequest(`graphs/${graph.id}/entities${initial?`/${initial.id}`:""}`,initial?"PUT":"POST",{name,kind,aliases:split(aliases),symbols:split(symbols),evidence:evidence.map(({document_id,page_number,start_offset,end_offset,quote})=>({document_id,page_number,start_offset,end_offset,quote})),...(initial?{expected_revision:initial.revision,reason}:{})});onSaved();
  }catch(err){setError(errorText(err,c));setBusy(false);}}
  return <GraphModal title={initial?c("Edit identity","修订实体"):c("Add an evidenced identity","添加有证据的实体")} onClose={onClose} busy={busy}><p>{c("Companies, groups and brands keep separate IDs. Matching names do not merge identities. Editing an identity returns accepted relationships to review.","公司、集团与品牌使用独立 ID，相同名称不会自动合并。修订实体后，已接受的相关关系需要重新审核。")}</p><form onSubmit={save}><fieldset disabled={busy}>
    <label>{c("Entity name","实体名称")}<input required maxLength={160} value={name} onChange={e=>setName(e.target.value)}/></label><label>{c("Entity type","实体类型")}<select value={kind} onChange={e=>setKind(e.target.value)}>{Object.entries(entityKinds).map(([v,label])=><option key={v} value={v}>{c(label[0],label[1])}</option>)}</select></label>
    <label>{c("Aliases, separated by commas","别名，用逗号分隔")}<input value={aliases} onChange={e=>setAliases(e.target.value)}/></label><label>{c("Symbols, separated by commas","证券代码，用逗号分隔")}<input value={symbols} onChange={e=>setSymbols(e.target.value)}/></label>
    <EvidencePicker graph={graph} value={evidence} onChange={setEvidence}/>{initial&&<label>{c("Revision reason","修订原因")}<textarea required value={reason} maxLength={1000} onChange={e=>setReason(e.target.value)}/></label>}{error&&<p role="alert" className="error-banner">{error}</p>}<button className="primary-button" disabled={busy||!evidence.length}>{busy?c("Saving…","保存中…"):c("Save identity","保存实体")}</button>
  </fieldset></form></GraphModal>;
}

export function RelationEditor({graph,initial,onClose,onSaved}:{graph:Graph;initial?:Relation;onClose:()=>void;onSaved:()=>void}){
  const c=useDocumentCopy();const [source,setSource]=useState(initial?.source_id||"");const [target,setTarget]=useState(initial?.target_id||"");const [kind,setKind]=useState(initial?.relation_type||graph.relation_types[0]);const [assertion,setAssertion]=useState(initial?.assertion||"disclosed");
  const [from,setFrom]=useState(initial?.valid_from||"");const [until,setUntil]=useState(initial?.valid_until||"");const [explanation,setExplanation]=useState(initial?.explanation||"");const [evidence,setEvidence]=useState<Evidence[]>(initial?.evidence||[]);
  const [reason,setReason]=useState("");const [error,setError]=useState("");const [busy,setBusy]=useState(false);
  async function save(event:React.FormEvent){event.preventDefault();setBusy(true);setError("");try{
    await researchRequest(`graphs/${graph.id}/relations${initial?`/${initial.id}`:""}`,initial?"PUT":"POST",{source_id:source,target_id:target,relation_type:kind,assertion:kind==="may_affect"?"inferred":assertion,valid_from:from||null,valid_until:until||null,explanation,
      evidence:evidence.map(({document_id,page_number,start_offset,end_offset,quote})=>({document_id,page_number,start_offset,end_offset,quote})),...(initial?{expected_revision:initial.revision,reason}:{})});onSaved();
  }catch(err){setError(errorText(err,c));setBusy(false);}}
  return <GraphModal title={initial?c("Revise relationship for review","修订关系并重新审核"):c("Propose a relationship","提交关系候选")} onClose={onClose} busy={busy}><p>{c("Evidence must support the relationship, not just mention both names. Inferred influence remains inference after acceptance.","证据必须支持关系本身，不能仅有名称共现。影响路径即使被接受也始终标注为推断。")}</p><form onSubmit={save}><fieldset disabled={busy}>
    <EntitySelector graphId={graph.id} value={source} onChange={setSource} label={c("Source identity","起点实体")}/><EntitySelector graphId={graph.id} value={target} onChange={setTarget} label={c("Target identity","终点实体")}/>
    <label>{c("Relationship type","关系类型")}<select value={kind} onChange={e=>{setKind(e.target.value);if(e.target.value==="may_affect")setAssertion("inferred");}}>{graph.relation_types.map(v=><option key={v} value={v}>{graphLabel(v,c)}</option>)}</select></label><label>{c("Evidence classification","证据分类")}<select value={kind==="may_affect"?"inferred":assertion} disabled={kind==="may_affect"||initial?.assertion==="inferred"} onChange={e=>setAssertion(e.target.value)}><option value="disclosed">{c("Direct disclosure","直接披露")}</option><option value="inferred">{c("Inference / hypothesis","推断 / 假设")}</option></select></label>
    <div className="form-grid"><label>{c("Applies from","适用起始日期")}<input type="date" value={from} onChange={e=>setFrom(e.target.value)}/></label><label>{c("Applies until (optional)","适用结束日期（可选）")}<input type="date" min={from} value={until} onChange={e=>setUntil(e.target.value)}/></label></div><small className="muted">{c("Unknown dates can be saved as candidates, but must be resolved before acceptance.","日期不明时可保留候选，接受之前必须核实日期。")}</small>
    <label>{c("Interpretation and limitations","关系说明与限制")}<textarea required maxLength={2000} rows={3} value={explanation} onChange={e=>setExplanation(e.target.value)}/></label><EvidencePicker graph={graph} value={evidence} onChange={setEvidence}/>
    {initial&&<label>{c("Revision reason","修订原因")}<textarea required maxLength={1000} value={reason} onChange={e=>setReason(e.target.value)}/></label>}{error&&<p role="alert" className="error-banner">{error}</p>}<button className="primary-button" disabled={busy||!evidence.length||source===target}>{busy?c("Saving…","保存中…"):c("Save candidate","保存候选")}</button>
  </fieldset></form></GraphModal>;
}
