"use client";

import { useT } from "@/hooks/use-language";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ReportComparisonResult } from "@/lib/report-comparison";
import type { Report } from "@/lib/research";

const price = (value: number | null) => value === null ? "—" : value.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
const percent = (value: number | null) => value === null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;

export function ComparisonPrices({ prices, reports, points, busy, visible, onPoints, onSource }: {
  prices: NonNullable<ReportComparisonResult["prices"]>; reports: Report[];
  points: number; busy: boolean; visible: boolean; onPoints: (points: number) => void;
  onSource: (report: Report, sourceId: string) => void;
}) {
  const t = useT();
  return <section className="finance-card comparison-prices" aria-label={t("同区间价格对照")} aria-busy={busy}>
    <div className="comparison-price-heading"><h2>{t("同区间价格对照")}</h2>
      <label>{t("共同成交日窗口")}<select value={points} disabled={busy} onChange={event => onPoints(Number(event.target.value))}>
        {[5, 20, 60].map(value => <option key={value} value={value}>{t("最近")}{t(value)}{t("日")}</option>)}
      </select></label>
    </div>
    <p className="field-note" role="status">{t(busy ? "正在核对所选窗口，暂显示上次成功的结果。" : `请求 ${prices.requested_points} 日，实际采用 ${prices.used_sessions} 个共同成交日。`)}</p>
    {prices.series.length > 0 ? <>
      <p>{t(prices.start_session)}{t("至")}{t(prices.end_session)}{t("· 首日收盘设为 100")}</p>
      <ul className="comparison-chart-key" aria-label={t("图例")}>{reports.map((report, index) => <li key={report.id}>
        <i className={`comparison-line-${index}`} aria-hidden="true" />{t(report.symbol)}
      </li>)}</ul>
      <div className="comparison-price-chart">{visible && <ResponsiveContainer width="100%" height="100%">
        <LineChart data={prices.series} margin={{ left: 0, right: 10, top: 10, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis dataKey="date" minTickGap={30} tickFormatter={value => value.slice(5)} tick={{ fill: "var(--finance-muted)", fontSize: 10 }} />
          <YAxis domain={["auto", "auto"]} width={44} tick={{ fill: "var(--finance-muted)", fontSize: 10 }} />
          <Tooltip contentStyle={{ background: "var(--finance-panel)", color: "var(--foreground)", border: "1px solid var(--border)", borderRadius: 8 }}
            formatter={value => typeof value === "number" ? value.toFixed(2) : value} />
          {reports.map((report, index) => <Line key={report.id} dataKey={`price_${index}`} name={report.symbol} type="linear"
            stroke={index === 0 ? "var(--finance-accent)" : "var(--comparison-secondary)"} strokeDasharray={index === 0 ? undefined : "5 3"}
            strokeWidth={2} dot={false} isAnimationActive={false} />)}
        </LineChart>
      </ResponsiveContainer>}</div>
    </> : <p className="muted">{t("共同成交日不足，暂不绘制价格曲线。报告观点和原始证据仍可逐项核对。")}</p>}
    <div className="comparison-columns">{prices.stats.map(stat => {
      const report = reports.find(item => item.id === stat.report_id)!;
      return <div key={stat.report_id} className="comparison-price-stat"><h3>{t(stat.symbol)}</h3>
        <p>{t("区间价格变化")}<strong>{t(percent(stat.change_pct))}</strong></p>
        <p>{t("首日")}{t(price(stat.start_close))}{t("→ 末日")}{t(price(stat.end_close))}</p>
        <p className="field-note">{t("报告最新有效行情：")}{t(stat.last_session ?? "缺失")}</p>
        <div className="workbench-actions">{stat.source_ids.map(sourceId => <button type="button" className="chat-config-toggle"
          key={sourceId} onClick={() => onSource(report, sourceId)}>{t("行情证据 [")}{t(sourceId)}]</button>)}</div>
      </div>;
    })}</div>
    <p className="field-note">{t("仅使用两份报告保存的未复权日线，按共同且有成交的日期对齐；不填补停牌或缺失日期。曲线值 = 当日收盘 ÷ 共同首日收盘 × 100。价格变化不含分红、复权、费用或汇率转换，不等于投资总回报；公司行动可能造成跳变。窗口覆盖不足时按实际日期展示，不自动外推。")}</p>
    {!!prices.gaps.length && <ul className="comparison-price-gaps">{prices.gaps.map((gap, index) => <li key={index}>{t(gap)}</li>)}</ul>}
    {!!prices.series.length && <details><summary>{t("逐日对照数值与计算口径")}</summary>
      <div className="comparison-metric-row comparison-metric-header"><span>{t("日期")}</span>{reports.map(report => <strong key={report.id}>{t(report.symbol)}</strong>)}</div>
      {prices.series.map(row => <div className="comparison-metric-row" key={row.date}><span>{t(row.date)}</span>
        <strong>{t(row.price_0.toFixed(2))}</strong><strong>{t(row.price_1.toFixed(2))}</strong></div>)}
    </details>}
  </section>;
}
