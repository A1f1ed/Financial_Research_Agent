"use client";

import { useT } from "@/hooks/use-language";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowUpRight, ChartNoAxesCombined, LoaderCircle } from "lucide-react";
import { researchRequest } from "./workbench-panels";
import { CandidateButton, ReviewCandidates, type useReviewCandidates } from "./review-candidates";
import { ReviewChecks, type CheckSeed } from "./review-checks";
import { MarketSentiment } from "./market-sentiment";
import { MarketFollowThrough } from "./market-follow-through";
import { MarketIndustryHistory } from "./market-industry-history";
import { ReviewScreen } from "./review-screen";

const samples = [
  { name: "宽基与风格", benchmark: "510300.SH", symbols: "510050.SH, 510500.SH, 159915.SZ, 588000.SH" },
  { name: "行业 ETF", benchmark: "510300.SH", symbols: "512480.SH, 512010.SH, 512880.SH, 516160.SH" },
];

type ReviewRow = { symbol: string; close: number; day_pct: number; volume_ratio: number | null; source: string; provider: string };
export type Review = {
  requested_date: string;
  session: string;
  previous_session: string;
  benchmark: ReviewRow;
  requested_count: number;
  symbols: string[];
  sample: Array<ReviewRow & { relative_pct: number }>;
  gaps: Array<{ symbol: string; reason: string }>;
};

const percent = (value: number) => `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
const localToday = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(new Date());

export function MarketReview({ visible, onResearch, checkSeed, onCheckSeed, onDismissCheck, onOpenReport, onOpenCandidateReport, candidates }: {
  visible: boolean;
  onResearch: (symbol: string, session: string, benchmark: string) => void;
  checkSeed: CheckSeed | null;
  onCheckSeed: (seed: CheckSeed) => void;
  onDismissCheck: (seed: CheckSeed) => void;
  onOpenReport: (id: string, index: number) => void;
  onOpenCandidateReport: (id: string) => void;
  candidates: ReturnType<typeof useReviewCandidates>;
}) {
  const t = useT();
  const [today] = useState(localToday);
  const [benchmark, setBenchmark] = useState(samples[0].benchmark);
  const [symbols, setSymbols] = useState(samples[0].symbols);
  const [review, setReview] = useState<Review | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sampleInput = useRef<HTMLInputElement>(null);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);

  const candidateButton = (symbol: string, session: string, origin: "sample" | "ladder" | "follow_through" | "industry") => review && <CandidateButton
    key={`${symbol}:${session}:${review.benchmark.symbol}:${origin}`}
    scope={{ symbol, session, benchmark: review.benchmark.symbol, origin }} candidates={candidates} />;
  const sentimentActions = (origin: "ladder" | "follow_through" | "industry") => (symbol: string, session: string) => review && <div className="sentiment-row-actions">
    <button type="button" className="chat-config-toggle" onClick={() => onResearch(symbol, session, review.benchmark.symbol)}>{t("研究该标的")}</button>
    {t(candidateButton(symbol, session, origin))}
  </div>;

  async function run(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (active.current) return;
    const asOf = new FormData(event.currentTarget).get("as_of");
    const sample = symbols.split(/[\s,，、]+/).filter(Boolean);
    if (sample.length < 1 || sample.length > 8) {
      setError("请输入 1 至 8 个证券代码，并以空格或逗号分隔。");
      return;
    }
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError("");
    try {
      const result = await researchRequest<Review>("market-review", "POST", { as_of: asOf, benchmark, symbols: sample }, controller.signal);
      if (!controller.signal.aborted) setReview(result);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "行情读取失败，请重试。");
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return <section className="workbench-page market-review">
    <div className="section-eyebrow">MARKET REVIEW</div>
    <h1><ChartNoAxesCombined size={23} />{t("A 股收盘复盘")}</h1>
    <p className="intro">{t("选定基准和样本，查看同一交易日的涨跌、相对强弱与量能，再挑选标的深入研究。")}</p>
    <form className="finance-card" onSubmit={run}>
      <fieldset disabled={busy}>
        <div className="workbench-actions review-presets" aria-label={t("样本预设")}>
          {samples.map(preset => <button type="button" key={preset.name} className="chat-config-toggle"
            onClick={() => { setBenchmark(preset.benchmark); setSymbols(preset.symbols); setError(""); }}>
            {t(preset.name)}
          </button>)}
        </div>
        <div className="form-grid">
          <label>{t("复盘日期")}<input name="as_of" type="date" defaultValue={today} min="2000-01-01" max={today} required /></label>
          <label>{t("基准代码")}<input value={benchmark} required maxLength={16} onChange={e => setBenchmark(e.target.value)} /></label>
          <label className="review-sample">{t("样本代码（最多 8 个）")}<input ref={sampleInput} value={symbols} required maxLength={160}
            placeholder="600519.SH, 300750.SZ" onChange={e => setSymbols(e.target.value)} /></label>
        </div>
        <p className="field-note">{t("使用带 .SH 或 .SZ 后缀的六位代码。样本涨跌分布只反映所选证券。")}</p>
      </fieldset>
      <div className="workbench-actions">
        <button className="primary-button" disabled={busy} type="submit">
          {busy && <LoaderCircle className="spin" size={16} />}{t(busy ? "读取日线…" : "查看收盘复盘")}
        </button>
      </div>
    </form>
    {error && <p className="error-banner" role="alert">{t(error)}</p>}
    <ReviewCandidates items={candidates.items} loading={candidates.loading} loadError={candidates.error} refresh={candidates.refresh}
      onResearch={onResearch} onOpenReport={onOpenCandidateReport}
      onFill={sample => { setSymbols(sample.join(", ")); setError(""); sampleInput.current?.focus(); }} />
    <section className="finance-card" aria-busy={busy} aria-label={t("复盘结果")}>
      {!review ? <p role={busy ? "status" : undefined} className="muted">{t(busy ? "正在核对基准与样本的交易日…" : "选择样本后，结果将在此显示。")}</p> : <>
        <div className="workbench-item-head"><h2>{t(review.session)}{t("收盘复盘")}</h2><span className="status-badge">{t("基准来源 ·")}{t(review.benchmark.provider)}</span></div>
        <p className="muted">{t("选定")}{t(review.requested_date)}{t("· 对照")}{t(review.previous_session)}{t("收盘")}{t(review.requested_date !== review.session && " · 使用基准最近可用的已收盘日")}</p>
        <div className="review-metrics">
          <div><small>{t("基准 ·")}{t(review.benchmark.symbol)}</small><strong>{t(percent(review.benchmark.day_pct))}</strong></div>
          <div><small>{t("有效样本 / 已选")}</small><strong>{t(review.sample.length)} / {t(review.requested_count)}</strong></div>
          <div><small>{t("样本上涨 / 平盘 / 下跌")}</small><strong>{t(review.sample.filter(row => row.day_pct > 0).length)} / {t(review.sample.filter(row => row.day_pct === 0).length)} / {t(review.sample.filter(row => row.day_pct < 0).length)}</strong></div>
        </div>
        <ul className="review-rows" aria-label={t("样本按当日涨跌排序")}>
          {review.sample.map(row => <li key={row.symbol}>
              <div><a href={row.source} target="_blank" rel="noreferrer">{t(row.symbol)} <ArrowUpRight size={12} /></a><small>{t(row.provider)}</small></div>
              <span>{t("收盘")}<strong>{t(row.close.toLocaleString("zh-CN", { maximumFractionDigits: 4 }))}</strong></span>
              <span>{t("当日")}<strong>{t(percent(row.day_pct))}</strong></span>
              <span>{t("相对基准")}<strong>{t(row.relative_pct > 0 ? "+" : "")}{t(row.relative_pct.toFixed(2))}{t("个百分点")}</strong></span>
              <span>{t("量比")}<strong>{t(row.volume_ratio === null ? "—" : `${row.volume_ratio.toFixed(2)}×`)}</strong></span>
              <div className="review-row-actions">
                <button className="chat-config-toggle" onClick={() => onResearch(row.symbol, review.session, review.benchmark.symbol)}>{t("研究该标的")}</button>
                <button className="chat-config-toggle" onClick={() => onCheckSeed({ symbol: row.symbol, benchmark: review.benchmark.symbol, baseline: review.session })}>{t("记录验证条件")}</button>
                {t(candidateButton(row.symbol, review.session, "sample"))}
              </div>
            </li>)}
        </ul>
        {!review.sample.length && <p className="muted">{t("当前样本缺少与基准日期对齐的有效数据。")}</p>}
        {!!review.gaps.length && <details><summary>{t("数据提示（")}{t(review.gaps.length)}）</summary>
          <ul>{review.gaps.map((gap, index) => <li key={index}>{t(gap.symbol)} · {t(gap.reason)}</li>)}</ul>
        </details>}
        <p className="field-note">{t("量比为当日成交量 ÷ 前 20 个有成交日的平均成交量。使用未复权日线，除权除息可能造成跳变。")}</p>
        <a className="source-link" href={review.benchmark.source} target="_blank" rel="noreferrer">{t("查看基准行情来源")}<ArrowUpRight size={12} /></a>
      </>}
    </section>
    {review?.symbols && <ReviewScreen review={review} onResearch={onResearch} />}
    {review && <MarketSentiment key={`sentiment:${review.session}`} session={review.session} renderActions={sentimentActions("ladder")} />}
    {review && <MarketFollowThrough key={`${review.previous_session}:${review.session}`} session={review.session}
      previous={review.previous_session} renderActions={sentimentActions("follow_through")} />}
    {review && <MarketIndustryHistory key={`industries:${review.session}`} session={review.session} renderActions={sentimentActions("industry")} />}
    <ReviewChecks visible={visible} seed={checkSeed} onDismiss={onDismissCheck} onOpenReport={onOpenReport} />
  </section>;
}
