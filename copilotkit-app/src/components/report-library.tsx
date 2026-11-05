"use client";

import { useState } from "react";
import { ArrowUpRight, BookOpen, Columns2, Trash2 } from "lucide-react";
import { formatReportTime, STATUS_NAMES, type ReportSummary } from "@/lib/research";

export function ReportLibrary({ reports, loading, error, refresh, onOpen, onArchive, onCompare, onNew }: {
  reports: ReportSummary[]; loading: boolean; error: string; refresh: () => Promise<void>;
  onOpen: (id: string) => void; onArchive: (id: string) => Promise<void>;
  onCompare: (ids: [string, string]) => void; onNew: () => void;
}) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");
  const [status, setStatus] = useState("all");
  const [selection, setSelection] = useState<string[]>([]);
  const [archiveTarget, setArchiveTarget] = useState<string | null>(null);
  const [archiving, setArchiving] = useState(false);
  const [archiveError, setArchiveError] = useState("");
  const chosen = reports.filter(report => selection.includes(report.id));
  const shown = reports.filter(report =>
    `${report.symbol} ${report.as_of} ${report.assessment?.summary ?? ""}`.toLowerCase().includes(query.trim().toLowerCase()) &&
    (kind === "all" || (kind === "stock" ? !report.workflow : !!report.workflow)) &&
    (status === "all" || report.status === status));

  async function archive(id: string) {
    setArchiving(true);
    setArchiveError("");
    try {
      await onArchive(id);
      setSelection(previous => previous.filter(value => value !== id));
      setArchiveTarget(null);
    } catch (failure) {
      setArchiveError(failure instanceof Error ? failure.message : "归档失败，请重试。");
    } finally {
      setArchiving(false);
    }
  }

  return <section className="library-view">
    <div className="section-eyebrow">RESEARCH LIBRARY</div><h1>让研究持续积累。</h1>
    <p className="intro">检索历史研究，选择同一标的的两份单股报告，对照观点、研究范围与各自的证据。</p>
    <div className="finance-card library-filters">
      <label>检索报告<input type="search" value={query} placeholder="证券代码、截止日期或摘要" onChange={event => setQuery(event.target.value)} /></label>
      <label>报告类型<select value={kind} onChange={event => setKind(event.target.value)}>
        <option value="all">全部类型</option><option value="stock">单股研究</option><option value="brief">定时简报</option>
      </select></label>
      <label>报告状态<select value={status} onChange={event => setStatus(event.target.value)}>
        <option value="all">全部状态</option>{Object.entries(STATUS_NAMES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select></label>
    </div>
    {error && <div className="error-banner" role="alert">报告库读取失败。
      <button type="button" className="chat-config-toggle" onClick={() => void refresh()}>重试读取</button>
    </div>}
    {loading && !reports.length && <div className="finance-card" role="status">正在读取报告库…</div>}
    {!!reports.length && <div className="library-compare-controls">
      <p className="field-note">显示 {shown.length} / {reports.length} 份。可对照已完成或部分完成的单股报告。
        {chosen.length > 0 && `已选 ${chosen.length} 份 · ${chosen[0].symbol}。`}</p>
      <div className="workbench-actions">
        {chosen.map(report => <span className="status-badge" key={report.id}>{report.symbol} · {report.as_of} · {formatReportTime(report.created_at)}</span>)}
        {!!chosen.length && <button type="button" className="chat-config-toggle" onClick={() => setSelection([])}>清除选择</button>}
        <button type="button" className="primary-button" disabled={chosen.length !== 2}
          onClick={() => onCompare([chosen[0].id, chosen[1].id])}><Columns2 size={15} />对照所选报告（{chosen.length}/2）</button>
      </div>
    </div>}
    {!loading && !error && !reports.length && <div className="finance-card empty-library"><BookOpen size={28} /><h3>第一份研究，从这里开始</h3>
      <p>完成、部分完成和停止的研究都会保留。</p><button onClick={onNew}>开始新的研究 →</button></div>}
    {!loading && !!reports.length && !shown.length && <p className="finance-card muted">没有匹配的报告。可以调整检索词或筛选条件。</p>}
    {shown.map(report => {
      const selected = selection.includes(report.id);
      const comparable = !report.workflow && ["complete", "partial"].includes(report.status);
      const selectable = comparable && (selected || !chosen.length || chosen.length < 2 && chosen[0].symbol === report.symbol);
      return <article className="finance-card library-report" key={report.id}>
        <div className="library-card">
          <div><span className={`status-badge ${report.status}`}>{STATUS_NAMES[report.status] || report.status}</span>
            <h2>{report.symbol}</h2><p>截至 {report.as_of} · {report.workflow ? "定时简报" : report.config?.analysts ? `${report.config.analysts.length} 位分析师` : "研究范围未知"}</p>
            <p>生成于 <time dateTime={report.created_at}>{formatReportTime(report.created_at)}</time>（北京时间）</p>
            <p className="field-note">报告编号 {report.id.slice(0, 8)}</p>
            <small>{report.assessment?.summary?.slice(0, 150) || "报告尚未形成最终结论"}</small>
          </div>
          <div className="library-report-actions">
            {comparable && <label className="candidate-label"><input type="checkbox" checked={selected} disabled={!selectable}
              aria-label={`选择对照 ${report.symbol} ${report.as_of} ${report.id.slice(0, 8)}`}
              onChange={() => setSelection(previous => selected ? previous.filter(id => id !== report.id) : [...chosen.map(item => item.id), report.id])} />加入对照</label>}
            <button type="button" className="chat-config-toggle" onClick={() => onOpen(report.id)}>阅读报告 <ArrowUpRight size={15} /></button>
            <button type="button" className="chat-config-toggle danger-button" disabled={archiving} aria-expanded={archiveTarget === report.id}
              onClick={() => { setArchiveError(""); setArchiveTarget(archiveTarget === report.id ? null : report.id); }}>
              <Trash2 size={14} />归档
            </button>
          </div>
        </div>
        {archiveTarget === report.id && <div className="delete-confirmation" role="group" aria-label="归档确认">
          <p>归档 {report.symbol} 截至 {report.as_of} 的这份报告后，报告及其证据将从报告库和对照入口隐藏。</p>
          {archiveError && <p role="alert">{archiveError}</p>}
          <div className="workbench-actions">
            <button type="button" className="chat-config-toggle" disabled={archiving} onClick={() => setArchiveTarget(null)}>取消</button>
            <button type="button" className="chat-config-toggle danger-button danger-confirm" disabled={archiving}
              onClick={() => void archive(report.id)}>{archiving ? "归档中…" : "确认归档"}</button>
          </div>
        </div>}
      </article>;
    })}
  </section>;
}
