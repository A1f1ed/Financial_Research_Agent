import type { Copy } from "@/components/documents/shared";
export type Evidence = { document_id:string; page_number:number; start_offset:number; end_offset:number; quote:string;
  document_version?:number; metadata_revision?:number; title?:string; published_on?:string|null; published_at?:string|null };
export type Graph = { id:string; name:string; description:string; revision:number; archived:boolean; projected_revision:number; projection_current:boolean;
  relation_types:string[]; scope:{ collection_ids:string[]; document_ids:string[]; as_of:string|null; as_of_at:string|null; market:string; mode:string };
  snapshot:{ collections:{id:string;name:string}[]; documents:{id:string;title:string;eligible:boolean;exclusion:string|null}[] };
  entity_count?:number; extracted_candidate_count?:number; relation_counts?:Record<string,number>; latest_projection?:{id:string;job_id:string;status:string;error:string|null;published:boolean}|null };
export type Entity = { id:string; name:string; kind:string; aliases:string[]; symbols:string[]; revision:number; archived:boolean; evidence:Evidence[] };
export type Relation = { id:string; source_id:string; target_id:string; source_name?:string; target_name?:string; relation_type:string; assertion:string; revision:number; status:string;
  valid_from:string|null; valid_until:string|null; explanation:string; evidence:Evidence[]; extraction_version:string };
export type GraphResult = { id:string; graph_id:string; graph_revision:number; projection_id:string; nodes:Entity[]; edges:Relation[];
  paths:{nodes:string[];edges:string[]}[]; truncated:boolean; elapsed_ms:number };
export const entityKinds = {company:["Listed company / company","上市公司 / 公司"],group:["Group","集团"],brand:["Brand","品牌"],product:["Product category","产品类别"],region:["Region","地区"],policy:["Policy","政策"],event:["Event","事件"],industry:["Industry","行业"],organization:["Institution / organization","机构 / 组织"]} as const;
export const relationKinds = {owns:["Owns","拥有"],brand_of:["Brand of","所属品牌"],produces:["Produces","生产"],operates_in:["Operates in","经营地区"],supplies:["Supplies","供应"],customer_of:["Customer of","客户关系"],applies_to:["Applies to","适用于"],announced:["Announced","发布"],supersedes:["Supersedes","替代"],may_affect:["May affect · inference","可能影响 · 推断"]} as const;
export function graphLabel(value:string,c:Copy){
  const labels:Record<string,readonly[string,string]>={...entityKinds,...relationKinds,candidate:["Awaiting review","待审核"],accepted:["Accepted","已接受"],rejected:["Rejected","已拒绝"],revoked:["Revoked","已撤销"],disclosed:["Source disclosure","原文披露"],inferred:["Inference","推断"],queued:["Queued","排队中"],running:["Running","运行中"],complete:["Complete","已完成"],failed:["Failed","失败"],cancelled:["Cancelled","已取消"]};
  return labels[value]?c(...labels[value]):value;
}
