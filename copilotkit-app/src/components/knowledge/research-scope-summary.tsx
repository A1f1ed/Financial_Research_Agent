"use client";
import {useDocumentCopy} from "@/components/documents/shared";
import {formatReportTime,type ResearchKnowledgeSnapshot} from "@/lib/research";

export function ResearchScopeSummary({scope}:{scope?:ResearchKnowledgeSnapshot|null}){
  const c=useDocumentCopy();if(!scope)return null;
  const reasons:Record<string,[string,string]>={published_after_cutoff:["Published after cutoff","公开时间晚于截止日"],publication_unknown:["Publication date unknown","公开日期未知"],document_archived:["Document archived","资料已归档"],original_removed:["Original removed","原文已移除"]};
  return <details className="knowledge-research-snapshot"><summary>{c("Pinned research documents","已固定的研究资料")} · {scope.eligible_count} {c("eligible","个符合截止日")} · {scope.excluded_count} {c("excluded","个已排除")}</summary>
    <p className="field-note">{scope.collections.map(item=>`${item.name} · r${item.revision}`).join(" / ")} · {scope.cutoff.as_of} · {scope.cutoff.market}</p><small>{c("Pinned at submission","提交时固定")} {formatReportTime(scope.pinned_at)} {c("(Beijing time)","（北京时间）")}. {c("Current availability is checked again at retrieval; later collection additions are excluded.","检索时再次核对当前可用性，集合后续新增文件不进入本次研究。")}</small>
    <ul>{scope.documents.map(item=><li key={item.id}>{item.title} · v{item.version} / m{item.metadata_revision} · {item.eligible?c("Eligible at submission","提交时符合范围"):item.exclusion&&reasons[item.exclusion]?c(...reasons[item.exclusion]):item.exclusion}</li>)}</ul>
  </details>;
}
