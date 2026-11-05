"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, ArrowUpRight, Columns2 } from "lucide-react";
import { formatReportTime, STAGE_NAMES, type Report } from "@/lib/research";
import { researchRequest } from "./workbench-panels";
import { CitationText } from "./research-citation";

const cleanText = (text: string) => text.replace(/\[S\d+\]/g, "").replace(/\s+/g, " ").trim();
const metrics = [["close", "收盘"], ["ma20", "MA20"], ["ma60", "MA60"], ["rsi14", "RSI14"]] as const;

export function ReportComparison({ ids, onBack, onOpen, onSource }: {
  ids: [string, string]; onBack: () => void;
  onOpen: (id: string) => void; onSource: (report: Report, sourceId: string) => void;
}) {
  const [reports, setReports] = useState<Report[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    let active = true;
    setError("");
    setReports(null);
    void Promise.all(ids.map(id => researchRequest<Report>(`reports/${id}`, "GET", undefined, controller.signal)))
      .then(values => {
        if (!active) return;
        if (values.some(value => value.workflow || !["complete", "partial"].includes(value.status)) ||
            values[0].symbol !== values[1].symbol || values[0].id === values[1].id) {
          throw new Error("请选择同一标的的两份已完成或部分完成的单股报告。");
        }
        if (values.some(value => !value.config || !Array.isArray(value.config.analysts) ||
            !value.evidence || !Array.isArray(value.evidence.sources) || !Array.isArray(value.evidence.gaps))) {
          throw new Error("报告记录缺少研究范围或证据，暂时无法对照。");
        }
        setReports(values.sort((left, right) => left.as_of.localeCompare(right.as_of) || left.created_at.localeCompare(right.created_at)));
      }).catch(failure => {
        if (active) setError(controller.signal.aborted ? "报告读取超时，请重试。" : failure instanceof Error ? failure.message : "报告读取失败。");
        controller.abort();
      }).finally(() => clearTimeout(timer));
    return () => { active = false; clearTimeout(timer); controller.abort(); };
  }, [ids, attempt]);

  const blocks = reports ? [
    { title: "研究摘要", values: reports.map(report => report.assessment?.summary ? [report.assessment.summary] : []) },
    { title: "核心观点", values: reports.map(report => report.assessment?.key_points ?? []) },
    { title: "风险", values: reports.map(report => report.assessment?.risks ?? []) },
    { title: "催化剂", values: reports.map(report => report.assessment?.catalysts ?? []) },
    { title: "结论失效条件", values: reports.map(report => report.assessment?.invalidation_conditions ?? []) },
    { title: "估值场景", values: reports.map(report => report.assessment?.valuation_scenarios ?? []) },
  ] : [];
  return <section className="workbench-page report-comparison">
    <button type="button" className="chat-config-toggle" onClick={onBack}><ArrowLeft size={14} />返回报告库</button>
    <div className="section-eyebrow">RESEARCH COMPARISON</div><h1><Columns2 size={23} />研究报告对照</h1>
    <p className="intro">按截止日期及生成时间排列。核对两次记录中的观点与证据，研究范围和数据口径会影响可比性。</p>
    {error && <div className="finance-card"><p role="alert" className="error-banner">{error}</p>
      <button type="button" className="chat-config-toggle" onClick={() => setAttempt(value => value + 1)}>重试读取</button></div>}
    {!reports && !error && <div className="finance-card" role="status">正在读取两份报告及各自的证据…</div>}
    {reports && <>
      <div className="comparison-columns">
        {reports.map((report, index) => <article className="finance-card comparison-heading" key={report.id}>
          <span className="mini-heading">{index === 0 ? "较早记录" : "较新记录"}</span><h2>{report.symbol}</h2>
          <p>截至 {report.as_of}</p><p>生成于 {formatReportTime(report.created_at)}（北京时间）</p>
          <p className="field-note">报告编号 {report.id.slice(0, 8)}</p>
          <p>研究观点 · {report.assessment?.stance ?? "尚未形成"}　风险 · {report.assessment?.risk_level ?? "尚未评估"}</p>
          <button type="button" className="chat-config-toggle" onClick={() => onOpen(report.id)}>阅读完整报告 <ArrowUpRight size={13} /></button>
          <details><summary>研究配置</summary><p>{report.config.question}</p>
            <p>基准 {report.config.benchmark} · 深度 {report.config.depth}</p>
            <p>{report.config.analysts.map(role => STAGE_NAMES[role] ?? role).join("、")}</p>
            <p>独立风险审查{report.config.include_risk ? "已启用" : "未启用"}</p>
          </details>
        </article>)}
      </div>
      <section className="finance-card" aria-label="报告指标对照">
        <h2>价格与技术指标</h2>
        <div className="comparison-metric-row comparison-metric-header"><span>指标</span>{reports.map(report => <strong key={report.id}>{report.as_of}<small>{String(report.evidence.metrics?.last_session ?? "行情日未知")}</small></strong>)}</div>
        {metrics.map(([key, label]) => <div className="comparison-metric-row" key={key}><span>{label}</span>{reports.map(report => {
          const value = report.evidence.metrics?.[key];
          return <strong key={report.id}>{typeof value === "number" && Number.isFinite(value) ? value.toFixed(key === "rsi14" ? 2 : 4) : "—"}</strong>;
        })}</div>)}
        <p className="field-note">指标沿用各报告未复权日线口径。公司行动、行情日期和来源差异需结合证据核对。</p>
      </section>
      {blocks.map(block => {
        const equal = block.values.every(value => value.length > 0) &&
          block.values[0].map(cleanText).join("\n") === block.values[1].map(cleanText).join("\n");
        return <section className="finance-card" key={block.title}>
          <div className="workbench-item-head"><h2>{block.title}</h2><span className="status-badge">{equal ? "文字一致" : "逐项对照"}</span></div>
          <div className="comparison-columns">{reports.map((report, index) => <div key={report.id}>
            <p className="mini-heading">{report.as_of} · {index === 0 ? "较早记录" : "较新记录"}</p>
            {block.values[index].length ? <ul className="finding-list">{block.values[index].map((text, item) => <li key={item}>
              <CitationText text={text} onSource={sourceId => onSource(report, sourceId)} />
            </li>)}</ul> : <p className="muted">这份报告未提供此项。</p>}
          </div>)}</div>
        </section>;
      })}
      <section className="finance-card"><h2>数据缺口与来源</h2><div className="comparison-columns">
        {reports.map((report, index) => <div key={report.id}>
          <p className="mini-heading">{report.as_of} · {index === 0 ? "较早记录" : "较新记录"}</p>
          <p>{report.evidence.sources.length} 条来源</p>
          {report.evidence.gaps.length ? <ul>{report.evidence.gaps.map((gap, item) => <li key={item}>{gap}</li>)}</ul>
            : <p className="muted">本报告未列出数据缺口。</p>}
          <details><summary>查看这份报告的来源</summary><ul className="comparison-sources">
            {report.evidence.sources.map(source => <li key={source.id}><button type="button" className="chat-config-toggle"
              onClick={() => onSource(report, source.id)}>{source.id} · {source.title}</button></li>)}
          </ul></details>
        </div>)}
      </div></section>
    </>}
  </section>;
}
