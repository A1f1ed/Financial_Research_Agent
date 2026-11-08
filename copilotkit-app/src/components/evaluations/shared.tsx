"use client";
import {useEffect,useRef} from "react";
import {X} from "lucide-react";
import {useDocumentCopy} from "@/components/documents/shared";
export function EvalDialog({title,onClose,children}:{title:string;onClose:()=>void;children:React.ReactNode}){
  const ref=useRef<HTMLDialogElement>(null);const c=useDocumentCopy();
  useEffect(()=>{const element=ref.current;element?.showModal();return()=>element?.close();},[]);
  return <dialog ref={ref} className="document-confirm-dialog evaluation-dialog" aria-label={title} onCancel={onClose}><div className="workbench-item-head"><h2>{title}</h2><button className="chat-config-toggle" onClick={onClose} aria-label={c("Close evaluation dialog","关闭评测弹窗")}><X size={17}/></button></div>{children}</dialog>;
}
export function Status({value}:{value:string}){
  const c=useDocumentCopy();const names:Record<string,[string,string]>={pending:["Pending","待执行"],in_flight:["Running","运行中"],queued:["Queued","排队中"],running:["Running","运行中"],passed:["Passed checks","规则通过"],failed:["Failed","失败"],partial:["Partial execution","部分执行"],complete:["Execution complete","执行完成"],unscored:["Unscored","未评分"],error:["Service/config error","服务或配置错误"],timeout:["Timeout","超时"],unsupported:["Unsupported","暂不支持"],budget_exceeded:["Budget exceeded","超出预算"],cancelled:["Cancelled","已取消"],interrupted:["Unknown outcome","结果未知"]};
  const label=names[value];return <span className={`status-badge ${["error","timeout","failed","budget_exceeded","interrupted"].includes(value)?"failed":value==="passed"?"complete":value}`}>{label?c(...label):value}</span>;
}
export const milliseconds=(value:number|null|undefined)=>value==null?"—":`${value.toFixed(1)} ms`;
