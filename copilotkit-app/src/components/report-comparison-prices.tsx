"use client";

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
  return <section className="finance-card comparison-prices" aria-label="同区间价格对照" aria-busy={busy}>
    <div className="comparison-price-heading"><h2>同区间价格对照</h2>
      <label>共同成交日窗口<select value={points} disabled={busy} onChange={event => onPoints(Number(event.target.value))}>
        {[5, 20, 60].map(value => <option key={value} value={value}>最近 {value} 日</option>)}
      </select></label>
    </div>
    <p className="field-note" role="status">{busy ? "正在核对所选窗口，暂显示上次成功的结果。" : `请求 ${prices.requested_points} 日，实际采用 ${prices.used_sessions} 个共同成交日。`}</p>
    {prices.series.length > 0 ? <>
      <p>{prices.start_session} 至 {prices.end_session} · 首日收盘设为 100</p>
      <ul className="comparison-chart-key" aria-label="图例">{reports.map((report, index) => <li key={report.id}>
        <i className={`comparison-line-${index}`} aria-hidden="true" />{report.symbol}
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
    </> : <p className="muted">共同成交日不足，暂不绘制价格曲线。报告观点和原始证据仍可逐项核对。</p>}
    <div className="comparison-columns">{prices.stats.map(stat => {
      const report = reports.find(item => item.id === stat.report_id)!;
      return <div key={stat.report_id} className="comparison-price-stat"><h3>{stat.symbol}</h3>
        <p>区间价格变化 <strong>{percent(stat.change_pct)}</strong></p>
        <p>首日 {price(stat.start_close)} → 末日 {price(stat.end_close)}</p>
        <p className="field-note">报告最新有效行情：{stat.last_session ?? "缺失"}</p>
        <div className="workbench-actions">{stat.source_ids.map(sourceId => <button type="button" className="chat-config-toggle"
          key={sourceId} onClick={() => onSource(report, sourceId)}>行情证据 [{sourceId}]</button>)}</div>
      </div>;
    })}</div>
    <p className="field-note">仅使用两份报告保存的未复权日线，按共同且有成交的日期对齐；不填补停牌或缺失日期。曲线值 = 当日收盘 ÷ 共同首日收盘 × 100。价格变化不含分红、复权、费用或汇率转换，不等于投资总回报；公司行动可能造成跳变。窗口覆盖不足时按实际日期展示，不自动外推。</p>
    {!!prices.gaps.length && <ul className="comparison-price-gaps">{prices.gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul>}
    {!!prices.series.length && <details><summary>逐日对照数值与计算口径</summary>
      <div className="comparison-metric-row comparison-metric-header"><span>日期</span>{reports.map(report => <strong key={report.id}>{report.symbol}</strong>)}</div>
      {prices.series.map(row => <div className="comparison-metric-row" key={row.date}><span>{row.date}</span>
        <strong>{row.price_0.toFixed(2)}</strong><strong>{row.price_1.toFixed(2)}</strong></div>)}
    </details>}
  </section>;
}
