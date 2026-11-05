"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import { ArrowUpRight, LoaderCircle } from "lucide-react";
import { researchRequest } from "./workbench-panels";

type Member = { code: string; symbol: string | null; name: string; days: number | null };
type IndustryHistory = {
  calendar_source: string;
  days: Array<{ session: string; total: number | null; classified: number; source: string;
    sample: Array<{ symbol: string; source: string }> }>;
  industries: Array<{ name: string; members: Array<Member[] | null> }>;
};

const INITIAL_ROWS = 6;

export function MarketIndustryHistory({ session, renderActions }: {
  session: string;
  renderActions: (symbol: string, session: string) => React.ReactNode;
}) {
  const [result, setResult] = useState<IndustryHistory | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<{ name: string; index: number } | null>(null);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);

  async function refresh() {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError("");
    try {
      const data = await researchRequest<IndustryHistory>(`market-industry-history?session=${encodeURIComponent(session)}`,
        "GET", undefined, controller.signal);
      if (!controller.signal.aborted) {
        setResult(data);
        setSelected(null);
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "暂时无法读取行业历史。");
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  const members = selected && result?.industries.find(row => row.name === selected.name)?.members[selected.index];
  const selectedDay = selected && result?.days[selected.index];
  const verified = result?.days.filter(day => day.total !== null).length ?? 0;
  const industries = result?.industries.filter(row => row.name.includes(filter.trim())) ?? [];

  return <section className="finance-card market-industry-history" aria-label="涨停行业走势" aria-busy={busy}>
    <div className="workbench-item-head"><h2>涨停行业走势</h2><span className="status-badge">近 5 个交易日</span></div>
    <p className="muted">对照各行业在涨停池中的每日数量。点数字查看当天入池标的。</p>
    <button type="button" className="chat-config-toggle" disabled={busy} onClick={() => void refresh()}>
      {busy && <LoaderCircle size={14} className="spin" />}{busy ? "正在核对各日行情池…" : result ? "刷新行业走势" : "查看行业走势"}
    </button>
    {error && <p role="alert" className="error-banner">{error}</p>}
    {result && <>
      <p className="field-note" role="status">已核验 {verified} / {result.days.length} 个交易日。{result.days.length < 5 && "参考日线不足 5 日。"}
        {verified < result.days.length && "缺档日期以 — 标记。"}</p>
      {!result.industries.length ? <p className="muted">这段时间暂无可比较的行业数据。</p> : <>
        {result.industries.length > INITIAL_ROWS && <label className="industry-history-filter">筛选行业
          <input type="search" value={filter} placeholder="例如：半导体" onChange={event => {
            setFilter(event.target.value);
            setSelected(null);
            setExpanded(false);
          }} />
        </label>}
        <table className="industry-history-table" aria-label="各行业每日入池数量">
          <thead><tr><th scope="col">行业</th>{result.days.map(day => <th key={day.session} scope="col">
            <time dateTime={day.session}>{day.session.slice(5)}</time></th>)}</tr></thead>
          <tbody>{!industries.length && <tr><td colSpan={result.days.length + 1}>没有匹配的行业。</td></tr>}
          {industries.slice(0, expanded ? undefined : INITIAL_ROWS).map(row => <Fragment key={row.name}><tr>
            <th scope="row">{row.name}</th>{row.members.map((cell, index) => {
              const day = result.days[index];
              const pressed = selected?.name === row.name && selected.index === index;
              return <td key={day.session}>{cell?.length ? <button type="button" aria-pressed={pressed}
                aria-label={`${day.session} ${row.name}，${cell.length} 只涨停`}
                onClick={() => setSelected(pressed ? null : { name: row.name, index })}>{cell.length}</button>
                : cell ? "0" : "—"}</td>;
            })}</tr>
            {selected?.name === row.name && selectedDay && !!members?.length && <tr>
              <td colSpan={result.days.length + 1} className="industry-detail-cell">
                <div className="review-check-form industry-history-detail">
                  <h3>{selectedDay.session} · {selected.name}</h3>
                  <ul className="review-checks">{members.map(member => <li className="workbench-item-head" key={member.code}>
                    <span>{member.name} · {member.symbol ?? member.code}{member.days ? ` · ${member.days} 板` : ""}</span>
                    {member.symbol && renderActions(member.symbol, selectedDay.session)}
                  </li>)}</ul>
                  <a className="source-link" href={selectedDay.source} target="_blank" rel="noreferrer">查看当日涨停池 <ArrowUpRight size={12} /></a>
                </div>
              </td>
            </tr>}
          </Fragment>)}</tbody>
          <tfoot><tr><th scope="row">已分类 / 全池</th>{result.days.map(day => <td key={day.session}>
            {day.total === null ? "—" : `${day.classified}/${day.total}`}</td>)}</tr></tfoot>
        </table>
        {industries.length > INITIAL_ROWS && <button type="button" className="chat-config-toggle" aria-expanded={expanded}
          onClick={() => { if (expanded) setSelected(null); setExpanded(!expanded); }}>
          {expanded ? "收起其余行业" : `查看全部 ${industries.length} 个行业`}
        </button>}
      </>}
      <details className="industry-history-sources"><summary>核对日期与来源</summary>
        <p className="field-note">按东方财富原始行业分类统计。0 表示已分类样本无该行业记录。日期取沪深 300 ETF 有成交日线，每日涨停池抽样对照腾讯日线。行业涨跌幅、资金流和题材归因需另取数据。</p>
        <div className="event-links"><a className="source-link" href={result.calendar_source} target="_blank" rel="noreferrer">沪深参考 ETF 日线 <ArrowUpRight size={12} /></a></div>
        <ul className="review-checks">{result.days.map(day => <li key={day.session}>
          <div className="event-links"><a href={day.source} target="_blank" rel="noreferrer">{day.session} 涨停池 <ArrowUpRight size={12} /></a>
            {day.sample.map(row => <a key={row.symbol} href={row.source} target="_blank" rel="noreferrer">{row.symbol} 样本日线 <ArrowUpRight size={12} /></a>)}
          </div>
          {day.total === null && <p className="muted">该日涨停池未通过核对。</p>}
        </li>)}</ul>
      </details>
    </>}
  </section>;
}
