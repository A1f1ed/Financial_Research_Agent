"use client";

import { useCallback } from "react";
import { useLanguage } from "@/hooks/use-language";

export function useDocumentCopy() {
  const { language } = useLanguage();
  return useCallback((english: string, chinese: string) => language === "en" ? english : chinese, [language]);
}
export type Copy = ReturnType<typeof useDocumentCopy>;
export const kinds = {
  annual_report: ["Annual report", "年度报告"], interim_report: ["Interim report", "中期报告"],
  quarterly_report: ["Quarterly report", "季度报告"], announcement: ["Announcement", "公司公告"],
  results_presentation: ["Results presentation", "业绩演示"], policy: ["Policy material", "政策材料"],
  research_material: ["Research material", "研究材料"], image: ["Image", "图片"],
} as const;
export type Metadata = {
  title: string; issuer: string; symbols: string; kind: string; source_url: string;
  published_on: string; published_at: string; publication_basis: string; period_start: string; period_end: string;
};
export type DocumentSummary = {
  id: string; title: string; issuer: string; symbols: string[]; kind: string; filename: string; media_type: string;
  byte_size: number; page_count: number; family_id: string; version: number; metadata_revision: number;
  status: string; archived: boolean; created_at: string; published_on: string | null; published_at: string | null;
  publication_precision: string; latest_job_id: string | null; removed_at: string | null;
};
export type DocumentDetail = DocumentSummary & {
  source_url: string | null; publication_basis: string; period_start: string | null; period_end: string | null;
  source_sha256: string; page_states: Record<string, number>; reference_count: number;
  versions: { id: string; version: number; title: string; archived: boolean }[];
};
export const emptyMetadata = (): Metadata => ({ title: "", issuer: "", symbols: "", kind: "research_material", source_url: "",
  published_on: "", published_at: "", publication_basis: "", period_start: "", period_end: "" });
export const metadataFrom = (document: DocumentDetail): Metadata => ({
  title: document.title, issuer: document.issuer, kind: document.kind, publication_basis: document.publication_basis,
  symbols: document.symbols.join(", "), source_url: document.source_url || "",
  published_on: document.published_on || "", published_at: document.published_at || "",
  period_start: document.period_start || "", period_end: document.period_end || "",
});
export function metadataPayload(value: Metadata, title = value.title) {
  return { ...value, title: title.trim(), symbols: value.symbols.split(",").map(item => item.trim()).filter(Boolean),
    source_url: value.source_url || null, published_on: value.published_on || null, published_at: value.published_at || null,
    period_start: value.period_start || null, period_end: value.period_end || null };
}
export function statusLabel(status: string, c: Copy) {
  const labels: Record<string, [string, string]> = {
    queued: ["Queued", "排队中"], processing: ["Processing", "处理中"], ready: ["Text extracted", "文字已提取"],
    partial: ["Partial · review coverage", "部分可用 · 请核对覆盖"], failed: ["Failed", "处理失败"],
    cancelled: ["Stopped", "已停止"], removed: ["Original removed", "原文已移除"],
    text_ready: ["Readable text", "文字可读"], needs_vision: ["Needs vision", "需要视觉识别"], pending: ["Not processed", "未处理"],
  };
  return labels[status] ? c(...labels[status]) : status;
}
export const sizeLabel = (bytes: number) => bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
export function errorText(error: unknown, c: Copy) {
  const message = error instanceof Error ? error.message : String(error);
  const known: Record<string, string> = {
    "Collection changed elsewhere; reload before applying this action": "集合已被其他操作修订，请关闭此操作、刷新集合后重试。",
    "Restore this collection before changing its contents": "请先恢复已归档集合，再修改内容。",
    "An archived collection cannot be used for new research": "已归档集合不能用于新研究，请先恢复。",
    "Restore unavailable documents before adding them to a collection": "请先恢复不可用的资料，再添加到集合。",
    "Document metadata changed elsewhere; reload before saving": "资料信息已被其他操作修改，请重新加载后保存。",
    "Restore this document before processing it": "请先恢复已归档资料，再重试处理。",
    "Document text is already processed": "文字已完成处理，无需重复执行。",
    "Document does not exist or its original has been removed": "资料不存在或原文已被移除。",
    "Only actual PDF, PNG and JPEG files are supported; renaming an extension is not sufficient": "仅支持真实的 PDF、PNG、JPEG 文件，修改扩展名不能转换格式。",
    "PDF is damaged, encrypted or unsupported; upload an unlocked valid PDF": "PDF 已损坏、被加密或不受支持，请上传有效的未加密 PDF。",
    "Use a direct HTTPS file link from a supported official issuer, exchange or policy source": "请使用支持的公司、交易所或政策官网的 HTTPS 文件直链。",
    "Document object storage is unavailable; existing metadata has been preserved": "原文存储暂不可用，已有资料信息已保留，请稍后重试。",
    "A newer document version exists; choose the latest version before uploading": "已有更新的资料版本，请先选择最新版本再上传。",
  };
  return c(message, known[message] || `操作未完成，请检查信息或重试。${message}`);
}

export function MetadataFields({ value, onChange, showTitle = true }: { value: Metadata; onChange: (next: Metadata) => void; showTitle?: boolean }) {
  const c = useDocumentCopy();
  const field = (key: keyof Metadata, next: string) => onChange({ ...value, [key]: next });
  return <div className="form-grid document-metadata-fields">
    {showTitle && <label className="document-wide">{c("Title", "标题")}<input required maxLength={250} value={value.title} onChange={event => field("title", event.target.value)} /></label>}
    <label>{c("Company / issuer", "公司 / 发布机构")}<input maxLength={200} value={value.issuer} onChange={event => field("issuer", event.target.value)} /></label>
    <label>{c("Symbols, separated by commas", "证券代码，用逗号分隔")}<input placeholder="1211.HK, 002594.SZ" value={value.symbols} onChange={event => field("symbols", event.target.value)} /></label>
    <label>{c("Material type", "材料类型")}<select value={value.kind} onChange={event => field("kind", event.target.value)}>
      {Object.entries(kinds).map(([key, labels]) => <option key={key} value={key}>{c(labels[0], labels[1])}</option>)}
    </select></label>
    <label>{c("Public release date · leave unknown if unverified", "公开日期 · 未核实请留空")}<input type="date" value={value.published_on} onChange={event => onChange({ ...value, published_on: event.target.value, published_at: "" })} /></label>
    <label className="document-wide">{c("Exact public time, if known (include timezone)", "准确公开时间（如已核实，须含时区）")}<input placeholder="2026-10-29T18:16:00+08:00" value={value.published_at} onChange={event => onChange({ ...value, published_at: event.target.value, published_on: "" })} /></label>
    <label className="document-wide">{c("Publication date verification basis", "公开日期核实依据")}<input required={!!(value.published_on || value.published_at)} maxLength={1000} value={value.publication_basis} onChange={event => field("publication_basis", event.target.value)} /></label>
    <label>{c("Reporting period start", "统计期间起日")}<input type="date" value={value.period_start} onChange={event => field("period_start", event.target.value)} /></label>
    <label>{c("Reporting period end", "统计期间止日")}<input type="date" value={value.period_end} onChange={event => field("period_end", event.target.value)} /></label>
    <label className="document-wide">{c("Original source URL (optional)", "原始来源链接（可选）")}<input type="url" value={value.source_url} onChange={event => field("source_url", event.target.value)} /></label>
    <small className="document-wide muted">{c("Uploading does not establish when a document became public. Unknown dates are excluded from strict historical research.", "上传时间不能证明公开时间。日期未核实的材料会从严格历史研究中排除。")}</small>
  </div>;
}
