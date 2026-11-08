"use client";
import {useRef,useState} from "react";
import {useDocumentCopy,errorText} from "@/components/documents/shared";
import {RunDialog} from "./run-dialog";
import {parseEvaluationDecision,type EvaluationDecision} from "./decision";
export function EvaluationStartCard({versionId,respond,status,result,onOpen}:{versionId?:string;respond?:(result:string)=>Promise<void>;status:string;result?:unknown;onOpen:(id:string)=>void}){
  const c=useDocumentCopy();const [open,setOpen]=useState(false);const [local,setLocal]=useState<EvaluationDecision|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState("");const lock=useRef(false);
  const decision=local||parseEvaluationDecision(result);
  async function finish(value:EvaluationDecision){
    if(lock.current||!respond)return;lock.current=true;setLocal(value);setBusy(true);setError("");setOpen(false);
    try{await respond(JSON.stringify(value.approved?value:{...value,status:"declined",run_created:false,notice:"The user declined. No evaluation was created. Acknowledge the refusal and stop; do not ask for approval again without a new user request."}));}catch(err){setError(errorText(err,c));lock.current=false;}finally{setBusy(false);}
  }
  return <div className="scope-card"><strong>{c("Review evaluation before starting","开始前核对评测范围")}</strong><p>{versionId}</p>
    {decision?.approved===false?<p role="status">{c("Evaluation request declined. No run was created.","已拒绝评测请求，未创建运行。")}</p>:decision?.approved?<><p role="status">{c("Evaluation run created after your approval.","经你确认后已创建评测运行。")}</p><button className="chat-config-toggle" onClick={()=>onOpen(decision.run_id)}>{c("Open evaluation run","打开评测运行")}</button></>:status==="executing"?<div className="document-actions"><button className="primary-button" disabled={!versionId||!respond||busy} onClick={()=>setOpen(true)}>{c("Review partition & budget","核对分区与预算")}</button><button className="chat-config-toggle" disabled={!respond||busy} onClick={()=>void finish({approved:false})}>{c("Decline","拒绝")}</button></div>:<small>{status==="complete"?c("User decision saved","已保存用户决定"):c("Preparing review…","正在准备核对…")}</small>}
    {busy&&<p role="status">{c("Recording your decision…","正在保存决定…")}</p>}{error&&<p role="alert">{error}{decision&&<button className="chat-config-toggle" disabled={busy} onClick={()=>void finish(decision)}>{c("Retry recording decision","重试保存决定")}</button>}</p>}
    {open&&versionId&&<RunDialog versionId={versionId} onClose={()=>setOpen(false)} onStarted={id=>void finish({approved:true,run_id:id})}/>}
  </div>;
}
