export const ANALYSTS = [
  { id: "fundamentals", name: "基本面分析师", subtitle: "财务质量、商业模式与估值依据", icon: "◫" },
  { id: "technical", name: "技术分析师", subtitle: "价格趋势、动量与量化指标", icon: "↗" },
  { id: "news", name: "新闻分析师", subtitle: "公司公告、新闻事件与催化剂", icon: "▤" },
  { id: "sentiment", name: "情绪分析师", subtitle: "社区样本、观点分歧与情绪偏差", icon: "◌" },
  { id: "index", name: "大盘分析师", subtitle: "基准走势与同期相对表现", icon: "⌁" },
  { id: "sector", name: "板块分析师", subtitle: "同业比较、行业驱动与风险", icon: "◴" },
] as const;
export type Analyst = typeof ANALYSTS[number]["id"];
export type ResearchConfig = {
  symbol: string; market: "HK" | "US" | "SH" | "SZ" | "SG"; as_of: string;
  analysts: Analyst[]; depth: "quick" | "standard" | "deep";
  include_risk: boolean; include_sentiment: boolean; question: string; benchmark: string; peers: string[];
};
export const DEFAULT_CONFIG: ResearchConfig = {
  symbol: "1211.HK", market: "HK", as_of: "2026-10-31", analysts: ANALYSTS.map(a => a.id),
  depth: "standard", include_risk: true, include_sentiment: true,
  question: "分析财务质量、增长驱动、估值依据、技术趋势与主要风险。", benchmark: "2800.HK", peers: ["175.HK", "2015.HK"],
};
export type Finding = { summary: string; stance: string; findings: string[]; risks: string[]; missing: string[]; source_ids: string[] };
export type Source = { id: string; title: string; kind: string; provider: string; content: string; published_at: string | null; url: string; excerpt_only?: boolean; event_date?: string; filing_url?: string | null };
export type Report = {
  workflow?: string;
  id: string; symbol: string; as_of: string; created_at: string; status: string; config: ResearchConfig; elapsed_seconds: number;
  evidence_coverage?: number; coverage_definition?: string;
  assessment?: { summary: string; stance: string; key_points: string[]; risks: string[]; catalysts: string[]; risk_level: string; valuation_scenarios: string[]; invalidation_conditions: string[] };
  stages: { id: string; status: string; detail?: string }[];
  findings: Record<string, Finding>;
  evidence: { sources: Source[]; gaps: string[]; bars: { date: string; close: number; volume?: number }[]; metrics: Record<string, unknown>; fetched_at?: string; methodology?: string; excluded_after_cutoff_or_undated?: number };
};
export type ReportSummary = Pick<Report, "id" | "symbol" | "as_of" | "created_at" | "status" | "config" | "assessment" | "workflow">;
const reportTime = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
export const formatReportTime = (value: string) => Number.isFinite(Date.parse(value)) ? reportTime.format(new Date(value)) : "时间未知";
export const STAGE_NAMES: Record<string, string> = {
  data: "证据采集", ...Object.fromEntries(ANALYSTS.map(a => [a.id, a.name])),
  bull: "多头研究", bear: "空头研究", risk: "风险审查", synthesis: "研究总结",
};
export const STATUS_NAMES: Record<string, string> = { pending: "等待", running: "进行中", complete: "已完成", partial: "部分完成", failed: "失败", cancelled: "已停止" };
