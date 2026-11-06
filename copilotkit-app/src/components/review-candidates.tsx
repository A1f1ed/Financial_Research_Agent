"use client";

import { useT } from "@/hooks/use-language";

import { useState, type FormEvent } from "react";
import { ArrowUpRight, Bookmark } from "lucide-react";
import { researchRequest, useResearchList } from "./workbench-panels";

const observationLabels = {
  legacy: "早期收藏", sample: "收盘样本", ladder: "连板梯队",
  follow_through: "昨涨停股次日表现", industry: "涨停行业走势", report: "单股报告",
};
type ObservationOrigin = keyof typeof observationLabels;
type Observation = {
  session: string; benchmark: string; origin: ObservationOrigin;
  source_url?: string; report_id?: string; report_available?: boolean;
};
type CandidateScope = Pick<Observation, "session" | "benchmark" | "report_id"> & {
  symbol: string; origin: Exclude<ObservationOrigin, "legacy">;
};
export type Candidate = Pick<CandidateScope, "symbol" | "session" | "benchmark"> & { note: string; observations: Observation[] };

export function useReviewCandidates(visible: boolean) {
  return useResearchList<Candidate>(visible ? "review-candidates" : null, "candidates", false);
}

export function CandidateButton({ scope, candidates }: {
  scope: CandidateScope;
  candidates: ReturnType<typeof useReviewCandidates>;
}) {
  const t = useT();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const candidate = candidates.items.find(item => item.symbol === scope.symbol);
  const saved = candidate?.observations.some(observation => observation.session === scope.session &&
    observation.benchmark === scope.benchmark && observation.origin === scope.origin && observation.report_id === scope.report_id);

  async function add() {
    setSaving(true);
    setError("");
    try {
      await researchRequest("review-candidates", "POST", scope);
      await candidates.refresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "加入候选池失败，请重试。");
    } finally {
      setSaving(false);
    }
  }

  return <div className="candidate-add">
    <button type="button" className="chat-config-toggle" disabled={saving || saved}
      onClick={() => void add()}>{t(saved ? "已记录观察" : saving ? "正在记录…" : candidate ? "记录本次观察" : "加入候选池")}</button>
    {error && <small role="alert" className="candidate-error">{t(error)}</small>}
  </div>;
}

export function ReviewCandidates({ items, loading, loadError, refresh, onFill, onResearch, onOpenReport }: {
  items: Candidate[];
  loading: boolean;
  loadError: string;
  refresh: () => Promise<void>;
  onFill: (symbols: string[]) => void;
  onResearch: (symbol: string, session: string, benchmark: string) => void;
  onOpenReport: (id: string) => void;
}) {
  const t = useT();
  const [selected, setSelected] = useState<string[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const sample = items.filter(item => selected.includes(item.symbol)).map(item => item.symbol);

  async function save(symbol: string, action: "PUT" | "DELETE", note?: string) {
    if (pending) return;
    setPending(true);
    setError("");
    setNotice("");
    try {
      await researchRequest(`review-candidates/${symbol}`, action, note === undefined ? undefined : { note });
      await refresh();
      if (action === "DELETE") setSelected(previous => previous.filter(value => value !== symbol));
      setEditing(null);
      setRemoving(null);
      setNotice(`${symbol} ${action === "DELETE" ? "已移出候选池" : "的备注已保存"}`);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "保存失败，请重试。");
    } finally {
      setPending(false);
    }
  }

  function submitNote(event: FormEvent<HTMLFormElement>, symbol: string) {
    event.preventDefault();
    void save(symbol, "PUT", String(new FormData(event.currentTarget).get("note") ?? ""));
  }

  return <details className="finance-card review-candidates">
    <summary><Bookmark size={16} aria-hidden="true" /> <strong>{t("研究候选池")}</strong> <span className="status-badge">{t(items.length)}{t("个标的")}</span></summary>
    <p className="field-note">{t("从复盘或单股报告记录观察。勾选最多 8 个标的填入样本，确认日期和基准后再运行。")}</p>
    {loading && <p role="status" className="muted">{t("正在读取候选池…")}</p>}
    {loadError && <div className="workbench-actions candidate-actions"><p className="muted">{t("候选池读取失败。")}</p>
      <button type="button" className="chat-config-toggle" onClick={() => void refresh()}>{t("重试读取")}</button>
    </div>}
    {!loading && !loadError && !items.length && <p className="muted">{t("还没有候选。先查看一次收盘复盘，即可从有效样本添加。")}</p>}
    {!!items.length && <>
      <div className="workbench-actions candidate-actions">
        <button type="button" className="chat-config-toggle" disabled={!sample.length || pending}
          onClick={() => { onFill(sample); setNotice(`已填入 ${sample.length} 个标的，可以调整日期和基准后查看复盘。`); }}>{t("填入复盘样本（")}{t(sample.length)}/8）
        </button>
        {!!sample.length && <button type="button" className="chat-config-toggle" onClick={() => setSelected([])}>{t("清除选择")}</button>}
      </div>
      <ul className="review-checks">
        {items.map(item => <li key={item.symbol}>
          <label className="candidate-label">
            <input type="checkbox" checked={selected.includes(item.symbol)}
              disabled={sample.length >= 8 && !selected.includes(item.symbol)}
              onChange={event => setSelected(previous => event.target.checked ? [...previous, item.symbol] : previous.filter(value => value !== item.symbol))} />
            <strong>{t(item.symbol)}</strong>
          </label>
          <p className="muted">{t("首次观察")}{t(item.session)}{t("· 基准")}{t(item.benchmark)}</p>
          {item.note && editing !== item.symbol && <p className="candidate-note">{t(item.note)}</p>}
          <div className="workbench-actions candidate-actions">
            <button type="button" className="chat-config-toggle" onClick={() => onResearch(item.symbol, item.session, item.benchmark)}>{t("按首次观察日研究")}</button>
            <button type="button" className="chat-config-toggle" disabled={pending} aria-expanded={editing === item.symbol}
              onClick={() => { setEditing(editing === item.symbol ? null : item.symbol); setRemoving(null); }}>
              {t(item.note ? "编辑备注" : "添加备注")}
            </button>
            <button type="button" className="chat-config-toggle danger-button" disabled={pending} aria-expanded={removing === item.symbol}
              aria-label={t(`移出 ${item.symbol}`)}
              onClick={() => { setRemoving(removing === item.symbol ? null : item.symbol); setEditing(null); }}>{t("移出")}</button>
          </div>
          <details className="candidate-history">
            <summary>{t("观察历史（")}{t(item.observations.length)}）</summary>
            <ul className="candidate-observations">
              {item.observations.map(observation => <li key={`${observation.session}:${observation.benchmark}:${observation.origin}:${observation.report_id ?? ""}`}>
                <p><strong>{t(observation.session)}</strong> · {t(observationLabels[observation.origin])}</p>
                <p className="muted">{t("基准")}{t(observation.benchmark)}</p>
                <div className="candidate-observation-actions">
                  <button type="button" className="chat-config-toggle"
                    onClick={() => onResearch(item.symbol, observation.session, observation.benchmark)}>{t("按观察日研究")}</button>
                  {observation.source_url && <a className="source-link" href={observation.source_url}
                    target="_blank" rel="noreferrer">{t("打开原始行情池")}<ArrowUpRight size={12} /></a>}
                  {t(observation.report_id && (observation.report_available
                    ? <button type="button" className="chat-config-toggle" onClick={() => onOpenReport(observation.report_id!)}>{t("查看来源报告")}</button>
                    : <small className="muted">{t("来源报告已归档或不可用")}</small>))}
                </div>
              </li>)}
            </ul>
          </details>
          {editing === item.symbol && <form className="review-check-form candidate-editor" onSubmit={event => submitNote(event, item.symbol)}>
            <label>{t("观察备注")}<textarea name="note" maxLength={280} rows={2} defaultValue={item.note} disabled={pending} /></label>
            <div className="workbench-actions candidate-actions">
              <button type="submit" className="chat-config-toggle" disabled={pending}>{t(pending ? "保存中…" : "保存备注")}</button>
              <button type="button" className="chat-config-toggle" disabled={pending} onClick={() => setEditing(null)}>{t("取消")}</button>
            </div>
          </form>}
          {removing === item.symbol && <div className="delete-confirmation" role="group" aria-label={t("移出确认")}>
            <p>{t("移出")}{t(item.symbol)}{t("会删除候选、备注和全部观察记录。")}</p>
            <div className="workbench-actions candidate-actions">
              <button type="button" className="chat-config-toggle danger-button danger-confirm" disabled={pending}
                onClick={() => void save(item.symbol, "DELETE")}>{t(pending ? "移出中…" : "确认移出")}</button>
              <button type="button" className="chat-config-toggle" disabled={pending} onClick={() => setRemoving(null)}>{t("取消")}</button>
            </div>
          </div>}
        </li>)}
      </ul>
    </>}
    {error && <p role="alert" className="error-banner">{t(error)}</p>}
    {notice && <p role="status" className="muted">{t(notice)}</p>}
  </details>;
}
