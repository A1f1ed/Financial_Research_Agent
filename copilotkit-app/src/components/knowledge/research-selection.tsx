"use client";

import {useState} from "react";
import {BookOpen,X,RefreshCw} from "lucide-react";
import {useDocumentCopy} from "@/components/documents/shared";
import {useKnowledgeResource,type Collection} from "./shared";
import type {ResearchConfig} from "@/lib/research";

export function ResearchKnowledgeSelection({config,onChange}:{config:ResearchConfig;onChange:(value:ResearchConfig)=>void}){
  const c=useDocumentCopy();const [open,setOpen]=useState(!!config.knowledge_collection_ids?.length);const [query,setQuery]=useState("");const [page,setPage]=useState(1);const [revision,setRevision]=useState(0);
  const selected=config.knowledge_collection_ids||[];
  const list=useKnowledgeResource<{collections:Collection[];total:number}>(open?`knowledge/collections?${new URLSearchParams({q:query,page:String(page),page_size:"10"})}`:null,revision,0);
  const [names,setNames]=useState<Record<string,string>>({});
  function toggle(item:Collection){setNames(previous=>({...previous,[item.id]:item.name}));onChange({...config,knowledge_collection_ids:selected.includes(item.id)?selected.filter(id=>id!==item.id):[...selected,item.id]});}
  return <details className="finance-card" open={open} onToggle={e=>setOpen(e.currentTarget.open)}><summary><BookOpen size={16}/> {c("Research documents","研究资料")} · {selected.length?`${selected.length} ${c("collections selected","个集合已选")}`:c("Optional","可选")}</summary>
    <p className="field-note">{c("Attach knowledge collections to this task. Submission fixes up to 50 file versions and the research cutoff above. Later collection additions do not enter this run. Unknown/future publication dates are excluded. Market evidence remains available.","可为本任务绑定知识集合。提交时固定最多 50 个文件版本及上方截止日期，后续新增资料不会混入本次运行。排除未知或未来公开日期；同时保留市场数据研究。")}</p>
    <div className="source-chips">{selected.map(id=><button type="button" key={id} onClick={()=>onChange({...config,knowledge_collection_ids:selected.filter(value=>value!==id)})} aria-label={c("Remove selected collection ","移除所选集合 ")+(names[id]||id)}>{names[id]||list.data?.collections.find(item=>item.id===id)?.name||id.slice(0,8)} <X size={12}/></button>)}</div>
    <label>{c("Find knowledge collections","查找知识集合")}<input value={query} onChange={e=>{setQuery(e.target.value);setPage(1);}}/></label>
    <div className="workbench-actions"><button type="button" className="chat-config-toggle" onClick={()=>setRevision(value=>value+1)}><RefreshCw size={14}/>{c("Refresh collections","刷新集合")}</button><small>{c("Up to eight collections","最多选择八个集合")}</small></div>
    {list.error&&<p role="alert" className="error-banner">{list.error}</p>}
    {list.loading&&!list.data&&<p role="status">{c("Loading collections…","正在读取集合…")}</p>}
    <div className="knowledge-chat-pick">{list.data?.collections.map(item=><label key={item.id}><input type="checkbox" checked={selected.includes(item.id)} disabled={selected.length>=8&&!selected.includes(item.id)} onChange={()=>toggle(item)}/><span>{item.name}<small>{item.coverage.documents} {c("versions","个版本")} · {item.coverage.text_pages} {c("readable pages","页可读文字")}</small></span></label>)}</div>
    {!list.loading&&list.data?.total===0&&<p>{c("No matching active collections. Add material in Knowledge base first.","没有匹配的有效集合，请先在知识库添加资料。")}</p>}
    <div className="document-pagination"><button type="button" className="chat-config-toggle" disabled={page<=1} onClick={()=>setPage(value=>value-1)}>{c("Previous","上一页")}</button><small>{page}</small><button type="button" className="chat-config-toggle" disabled={page*10>=(list.data?.total||0)} onClick={()=>setPage(value=>value+1)}>{c("Next","下一页")}</button></div>
    {!!selected.length&&<label>{c("Document retrieval mode","资料检索方式")}<select value={config.knowledge_search_mode||"keyword"} onChange={e=>onChange({...config,knowledge_search_mode:e.target.value as "keyword"|"hybrid"})}><option value="keyword">{c("Keyword · no embedding request","关键词 · 不请求向量模型")}</option><option value="hybrid">{c("Hybrid · requires configured embeddings and indices","混合 · 需配置向量模型与索引")}</option></select></label>}
  </details>;
}
