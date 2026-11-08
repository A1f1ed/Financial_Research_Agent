"use client";
import {useState} from "react";
import {useDocumentCopy} from "@/components/documents/shared";
import {RunDialog} from "./run-dialog";
export function EvaluationStartCard({versionId,respond,status,onOpen}:{versionId?:string;respond?:(result:string)=>void;status:string;onOpen:(id:string)=>void}){
  const c=useDocumentCopy();const [open,setOpen]=useState(false);const [started,setStarted]=useState<string|null>(null);
  return <div className="scope-card"><strong>{c("Review evaluation before starting","开始前核对评测范围")}</strong><p>{versionId}</p>{status==="executing"&&!started?<div className="document-actions"><button className="primary-button" disabled={!versionId} onClick={()=>setOpen(true)}>{c("Review partition & budget","核对分区与预算")}</button><button className="chat-config-toggle" onClick={()=>respond?.(JSON.stringify({approved:false}))}>{c("Decline","拒绝")}</button></div>:<small>{c("User decision saved","已保存用户决定")}</small>}{started&&<button className="chat-config-toggle" onClick={()=>onOpen(started)}>{c("Open evaluation run","打开评测运行")}</button>}{open&&versionId&&<RunDialog versionId={versionId} onClose={()=>setOpen(false)} onStarted={id=>{setOpen(false);setStarted(id);respond?.(JSON.stringify({approved:true,run_id:id,url:`/?evaluationRun=${id}`}));}}/>}</div>;
}
