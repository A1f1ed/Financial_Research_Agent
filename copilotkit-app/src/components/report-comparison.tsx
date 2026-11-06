"use client";

import { useT } from "@/hooks/use-language";

import { useEffect, useState } from "react";
import { ArrowLeft, ArrowUpRight, Columns2 } from "lucide-react";
import { formatReportTime, STAGE_NAMES, type Report } from "@/lib/research";
import type { ReportComparisonResult } from "@/lib/report-comparison";
import { researchRequest } from "./workbench-panels";
import { CitationText } from "./research-citation";
import { ComparisonPrices } from "./report-comparison-prices";

const cleanText = (text: string) => text.replace(/\[S\d+\]/g, "").replace(/\s+/g, " ").trim();
const metrics = [["close", "收盘"], ["ma20", "MA20"], ["ma60", "MA60"], ["rsi14", "RSI14"]] as const;

export function ReportComparison({ ids, visible, onBack, onOpen, onSource }: {
  ids: [string, string]; visible: boolean; onBack: () => void;
  onOpen: (id: string) => void; onSource: (report: Report, sourceId: string) => void;
}) {
  const t = useT();
  const [result, setResult] = useState<ReportComparisonResult | null>(null);
  const [points, setPoints] = useState(20);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!visible) return;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    let active = true;
    setError("");
    setBusy(true);
    void researchRequest<ReportComparisonResult>("report-comparisons", "POST", { report_ids: ids, points }, controller.signal)
      .then(value => {
        if (!active) return;
        setResult(value);
      }).catch(failure => {
        if (active) setError(controller.signal.aborted ? "报告读取超时，请重试。" : failure instanceof Error ? failure.message : "报告读取失败。");
        controller.abort();
      }).finally(() => { clearTimeout(timer); if (active) setBusy(false); });
    return () => { active = false; clearTimeout(timer); controller.abort(); };
  }, [ids, points, attempt, visible]);

  const current = result?.reports.length === 2 && result.reports.every(report => ids.includes(report.id)) ? result : null;
  const reports = current?.reports;
  const crossSection = current?.mode === "cross_section";
  const recordLabel = (index: number) => crossSection ? reports![index].symbol : index === 0 ? "较早记录" : "较新记录";

  const blocks = reports ? [
    { title: "研究摘要", values: reports.map(report => report.assessment?.summary ? [report.assessment.summary] : []) },
    { title: "核心观点", values: reports.map(report => report.assessment?.key_points ?? []) },
    { title: "风险", values: reports.map(report => report.assessment?.risks ?? []) },
    { title: "催化剂", values: reports.map(report => report.assessment?.catalysts ?? []) },
    { title: "结论失效条件", values: reports.map(report => report.assessment?.invalidation_conditions ?? []) },
    { title: "估值场景", values: reports.map(report => report.assessment?.valuation_scenarios ?? []) },
  ] : [];
  return <section className="workbench-page report-comparison">
    <button type="button" className="chat-config-toggle" onClick={onBack}><ArrowLeft size={14} />{t("返回报告库")}</button>
    <div className="section-eyebrow">RESEARCH COMPARISON</div><h1><Columns2 size={23} />{t("研究报告对照")}</h1>
    <p className="intro">{t(!current ? "正在核对所选报告的研究范围。" : crossSection ? "同一截止日的双标的研究，按证券代码排列。" : "同一标的按截止日期及生成时间排列。")}{t("核对观点、风险和各自的证据，研究范围和数据口径会影响可比性。")}</p>
    {error && <div className="finance-card"><p role="alert" className="error-banner">{t(error)}</p>
      <button type="button" className="chat-config-toggle" onClick={() => setAttempt(value => value + 1)}>{t("重试读取")}</button></div>}
    {!reports && !error && <div className="finance-card" role="status">{t("正在读取两份报告及各自的证据…")}</div>}
    {reports && <>
      <div className="comparison-columns">
        {reports.map((report, index) => <article className="finance-card comparison-heading" key={report.id}>
          <span className="mini-heading">{t(crossSection ? "同日研究" : recordLabel(index))}</span><h2>{t(report.symbol)}</h2>
          <p>{t("截至")}{t(report.as_of)}</p><p>{t("生成于")}{t(formatReportTime(report.created_at))}{t("（北京时间）")}</p>
          <p className="field-note">{t("报告编号")}{t(report.id.slice(0, 8))}</p>
          <p>{t("研究观点 ·")}{t(report.assessment?.stance ?? "尚未形成")}{t("风险 ·")}{t(report.assessment?.risk_level ?? "尚未评估")}</p>
          <button type="button" className="chat-config-toggle" onClick={() => onOpen(report.id)}>{t("阅读完整报告")}<ArrowUpRight size={13} /></button>
          <details><summary>{t("研究配置")}</summary><p>{t(report.config.question)}</p>
            <p>{t("基准")}{t(report.config.benchmark)}{t("· 深度")}{t(report.config.depth)}</p>
            <p>{report.config.analysts.map(role => t(STAGE_NAMES[role] ?? role)).join(t("、"))}</p>
            <p>{t("独立风险审查")}{t(report.config.include_risk ? "已启用" : "未启用")}</p>
          </details>
        </article>)}
      </div>
      {crossSection && current.prices && <ComparisonPrices prices={current.prices} reports={reports}
        points={points} busy={busy} visible={visible} onPoints={setPoints} onSource={onSource} />}
      <section className="finance-card" aria-label={t("报告指标对照")}>
        <h2>{t("价格与技术指标")}</h2>
        <div className="comparison-metric-row comparison-metric-header"><span>{t("指标")}</span>{reports.map(report => <strong key={report.id}>{t(crossSection ? report.symbol : report.as_of)}<small>{t(String(report.evidence.metrics?.last_session ?? "行情日未知"))}</small></strong>)}</div>
        {metrics.map(([key, label]) => <div className="comparison-metric-row" key={key}><span>{t(label)}</span>{reports.map(report => {
          const value = report.evidence.metrics?.[key];
          return <strong key={report.id}>{t(typeof value === "number" && Number.isFinite(value) ? value.toFixed(key === "rsi14" ? 2 : 4) : "—")}</strong>;
        })}</div>)}
        <p className="field-note">{t("指标沿用各报告未复权日线口径，行情日可能不同。收盘和均线是各标的的原币价格，价格高低不能用于判断估值贵贱；公司行动和来源差异需结合证据核对。")}</p>
      </section>
      {blocks.map(block => {
        const equal = block.values.every(value => value.length > 0) &&
          block.values[0].map(cleanText).join("\n") === block.values[1].map(cleanText).join("\n");
        return <section className="finance-card" key={block.title}>
          <div className="workbench-item-head"><h2>{t(block.title)}</h2><span className="status-badge">{t(equal ? "文字一致" : "逐项对照")}</span></div>
          <div className="comparison-columns">{reports.map((report, index) => <div key={report.id}>
            <p className="mini-heading">{t(report.as_of)} · {t(recordLabel(index))}</p>
            {block.values[index].length ? <ul className="finding-list">{block.values[index].map((text, item) => <li key={item}>
              <CitationText text={text} onSource={sourceId => onSource(report, sourceId)} />
            </li>)}</ul> : <p className="muted">{t("这份报告未提供此项。")}</p>}
          </div>)}</div>
        </section>;
      })}
      <section className="finance-card"><h2>{t("数据缺口与来源")}</h2><div className="comparison-columns">
        {reports.map((report, index) => <div key={report.id}>
          <p className="mini-heading">{t(report.as_of)} · {t(recordLabel(index))}</p>
          <p>{t(report.evidence.sources.length)}{t("条来源")}</p>
          {report.evidence.gaps.length ? <ul>{report.evidence.gaps.map((gap, item) => <li key={item}>{t(gap)}</li>)}</ul>
            : <p className="muted">{t("本报告未列出数据缺口。")}</p>}
          <details><summary>{t("查看这份报告的来源")}</summary><ul className="comparison-sources">
            {report.evidence.sources.map(source => <li key={source.id}><button type="button" className="chat-config-toggle"
              onClick={() => onSource(report, source.id)}>{t(source.id)} · {source.title}</button></li>)}
          </ul></details>
        </div>)}
      </div></section>
    </>}
  </section>;
}
