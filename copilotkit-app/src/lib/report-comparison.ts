import type { Report, ReportSummary } from "./research";

const marketGroup = (symbol: string) => {
  const market = symbol.split(".").pop();
  return market === "SH" || market === "SZ" ? "CN" : market;
};

export const canCompareReports = (left: ReportSummary, right: ReportSummary) =>
  left.id !== right.id && (left.symbol === right.symbol ||
    left.as_of === right.as_of && marketGroup(left.symbol) === marketGroup(right.symbol));

export type ReportComparisonResult = {
  mode: "history" | "cross_section";
  reports: Report[];
  prices: null | {
    requested_points: number; common_sessions: number; used_sessions: number;
    start_session: string | null; end_session: string | null;
    series: { date: string; price_0: number; price_1: number }[];
    stats: { report_id: string; symbol: string; last_session: string | null; valid_sessions: number;
      source_ids: string[]; start_close: number | null; end_close: number | null; change_pct: number | null }[];
    gaps: string[];
  };
};
