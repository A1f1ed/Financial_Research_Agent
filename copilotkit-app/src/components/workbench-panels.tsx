"use client";

import { AISettingsPanel } from "@/components/ai-settings";
import { EmbeddingSettingsPanel } from "@/components/knowledge/embedding-settings";
import { useT, type Translate } from "@/hooks/use-language";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUpRight, CalendarClock, ClipboardList, Database, Play, Plus, Settings2, Trash2 } from "lucide-react";
import { DEFAULT_CONFIG, STATUS_NAMES, type ResearchConfig } from "@/lib/research";

type ScheduleDraft = {
  name: string;
  config: ResearchConfig;
  repeat: "hourly" | "daily" | "weekdays" | "weekly" | "trading_days";
  time: string;
  weekday: number;
  enabled: boolean;
  timing?: "clock" | "before_open" | "after_close";
  offset_minutes?: number;
  workflow: Workflow;
  symbols: string[];
  keyword: string;
  window_hours: number;
  move_threshold: number;
};
type Schedule = ScheduleDraft & { id: string; next_run: string | null };
type Task = {
  id: string; name: string; symbol: string; kind: "manual" | "scheduled" | "document" | "knowledge";
  status: string; created_at: string; error?: string; report_id?: string; managed?: boolean;
  trigger?: "manual" | "clock"; summary?: string;
};
const WORKFLOWS = {
  stock: ["单股深度研究", "跟踪一家公司，复用分析师、交叉审查与证据报告。"],
  morning: ["市场晨报", "对比一篮子市场代表标的的最近收盘表现，汇总近期市场要闻。"],
  news: ["要闻综述", "按主题关键词检索近期新闻，按时间排序并合并重复标题。"],
  watch: ["自选股异动", "对指定标的计算最近两个完整收盘的涨跌幅，突出达到阈值的标的。"],
  filings: ["公告追踪", "查找指定公司在时间窗口内的公告，保留发布时间和原文入口。"],
  weekly: ["每周自选复盘", "对比自选标的最近五个完整交易日的收盘变化。"],
} as const;
type Workflow = keyof typeof WORKFLOWS;
const MARKET = { HK: "港股", US: "美股", SH: "沪市", SZ: "深市", SG: "新加坡" };
const BENCHMARK = { HK: "2800.HK", US: "SPY.US", SH: "510300.SH", SZ: "159919.SZ", SG: "ES3.SG" };
const REPEAT = { hourly: "每小时", daily: "每天", trading_days: "每交易日", weekdays: "周一至周五", weekly: "每周" };
const WEEK = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const statusLabels: Record<string, string> = { ...STATUS_NAMES, queued: "等待执行", running: "运行中" };
const displayTime = (value: string) => new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
const canDeleteTask = (status: string) => ["complete", "partial", "failed", "cancelled"].includes(status);

type DeleteItem = { path: string; name: string };

function useDeletion(onDeleted: (paths: string[]) => Promise<void>) {
  const [selected, setSelected] = useState<string[]>([]);
  const [target, setTarget] = useState<{ anchor: string; items: DeleteItem[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const reset = () => { setTarget(null); setError(""); };
  const toggle = (path: string) => {
    reset();
    setSelected(items => items.includes(path) ? items.filter(item => item !== path) : [...items, path]);
  };
  const request = (anchor: string, items: DeleteItem[]) => { setError(""); setTarget({ anchor, items }); };
  async function remove() {
    if (!target || busy) return;
    setBusy(true);
    setError("");
    try {
      const results = await Promise.allSettled(target.items.map(item => researchRequest(item.path, "DELETE")));
      const failed = target.items.filter((_, index) => results[index].status === "rejected");
      const removed = target.items.filter(item => !failed.includes(item)).map(item => item.path);
      setSelected(items => items.filter(path => !removed.includes(path)));
      if (removed.length) await onDeleted(removed);
      if (failed.length) {
        const failure = results.find(result => result.status === "rejected");
        setError(`有 ${failed.length} 项未删除。${failure?.status === "rejected" ? String(failure.reason) : ""}`);
        setTarget({ ...target, items: failed });
      } else setTarget(null);
    } finally { setBusy(false); }
  }
  return { selected, target, busy, error, reset, toggle, request, remove };
}

function DeleteConfirmation({ deletion, anchor, plans, blocked = false }: {
  deletion: ReturnType<typeof useDeletion>; anchor: string; plans: boolean; blocked?: boolean;
}) {
  const t = useT();
  const { target, busy, error, reset, remove } = deletion;
  if (target?.anchor !== anchor) return null;
  const label = target.items.length === 1 ? `「${target.items[0].name}」` : `${target.items.length} 项`;
  return <div className="delete-confirmation" role="group" aria-label={t("删除确认")}>
    <p>{t(plans ? `删除${label}后将停止后续调度，已有执行记录和报告会保留。`
      : `从执行记录移除${label}？已有报告和所属计划的执行历史会保留。`)}</p>
    {error && <p role="alert">{t(error)}</p>}
    <div className="workbench-actions">
      <button className="chat-config-toggle" disabled={busy} onClick={reset}>{t("取消")}</button>
      <button className="chat-config-toggle danger-button danger-confirm" disabled={busy || blocked} onClick={() => void remove()}>{t(busy ? "删除中…" : "确认删除")}</button>
    </div>
  </div>;
}

function DeleteSelection({ deletion, items, plans, blocked }: {
  deletion: ReturnType<typeof useDeletion>; items: DeleteItem[]; plans: boolean; blocked?: boolean;
}) {
  const t = useT();
  const chosen = items.filter(item => deletion.selected.includes(item.path));
  if (!chosen.length) return null;
  return <div className="workbench-batch-delete">
    <button className="chat-config-toggle danger-button" disabled={deletion.busy} onClick={() => deletion.request("batch", chosen)}>
      <Trash2 size={14} />{t("删除所选（")}{t(chosen.length)}）
    </button>
    <DeleteConfirmation deletion={deletion} anchor="batch" plans={plans} blocked={blocked} />
  </div>;
}

export async function researchRequest<T>(path: string, method = "GET", body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/research/${path}`, {
    method, cache: "no-store", signal,
    ...(body !== undefined ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
  });
  const data = await response.json();
  if (!response.ok) {
    const message = typeof data.detail === "string" ? data.detail
      : Array.isArray(data.detail) ? data.detail[0]?.msg : data.error;
    throw new Error(message || "请求失败，请稍后重试。");
  }
  return data;
}

export function useResearchList<T extends object, M extends object = Record<string, never>>(path: string | null, key: string, poll = true) {
  const [items, setItems] = useState<T[]>([]);
  const [metadata, setMetadata] = useState<M | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const refreshRef = useRef<() => Promise<void>>(async () => {});
  const refresh = useCallback(() => refreshRef.current(), []);
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let pending: Promise<void> | undefined;
    let active = false;
    let revision = 0;
    const fetchList = async () => {
      clearTimeout(timer);
      const requested = revision;
      try {
        const result = await researchRequest<Record<string, T[]> & { meta?: M }>(path, "GET", undefined, controller.signal);
        if (controller.signal.aborted || requested !== revision) return;
        setItems(result[key]);
        setMetadata(result.meta ?? null);
        active = result[key].some(item => ("status" in item && (item.status === "queued" || item.status === "running")) ||
          ("repeat" in item && item.repeat === "trading_days" && "enabled" in item && item.enabled === true &&
            "next_run" in item && item.next_run === null) ||
          ("next_attempt_at" in item && typeof item.next_attempt_at === "string" && Date.parse(item.next_attempt_at) <= Date.now()));
        setError("");
      } catch (err) {
        if (!controller.signal.aborted && requested === revision) setError(String(err));
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          if (poll && !document.hidden) timer = setTimeout(() => { if (!document.hidden) void run(); }, active ? 3000 : 15000);
        }
      }
    };
    function run() {
      if (controller.signal.aborted) return Promise.resolve();
      return pending ??= fetchList().finally(() => { pending = undefined; });
    }
    refreshRef.current = async () => {
      revision++;
      if (pending) await pending;
      await run();
    };
    const visibility = () => { if (document.hidden) clearTimeout(timer); else void run(); };
    document.addEventListener("visibilitychange", visibility);
    if (!document.hidden) void run();
    return () => {
      controller.abort();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [path, key, poll]);
  return { items, metadata, error, loading, refresh };
}

const presets = [
  { name: "港股晨报", workflow: "morning", market: "HK", time: "09:00", repeat: "trading_days", weekday: 0, timing: "before_open", offset_minutes: 30 },
  { name: "美股晨报", workflow: "morning", market: "US", time: "08:00", repeat: "trading_days", weekday: 0, timing: "before_open", offset_minutes: 90 },
  { name: "快讯巡检", workflow: "news", market: "HK", time: "09:05", repeat: "hourly", weekday: 0, timing: "clock", offset_minutes: 30 },
  { name: "自选股异动", workflow: "watch", market: "HK", time: "18:00", repeat: "trading_days", weekday: 0, timing: "after_close", offset_minutes: 120 },
  { name: "沪深收盘异动", workflow: "watch", market: "SH", time: "15:30", repeat: "trading_days", weekday: 0, timing: "after_close", offset_minutes: 30 },
  { name: "公司公告追踪", workflow: "filings", market: "HK", time: "19:00", repeat: "daily", weekday: 0, timing: "clock", offset_minutes: 30 },
  { name: "每周自选复盘", workflow: "weekly", market: "HK", time: "09:00", repeat: "weekly", weekday: 5, timing: "clock", offset_minutes: 30 },
  { name: "单股深度研究", workflow: "stock", market: "HK", time: "09:00", repeat: "weekly", weekday: 5, timing: "clock", offset_minutes: 30 },
] as const;

function describeTiming(item: Pick<ScheduleDraft, "timing" | "offset_minutes" | "time">, t: Translate) {
  if (item.timing === "before_open") return t(`开盘前 ${item.offset_minutes ?? 30} 分钟`);
  if (item.timing === "after_close") return t(`收盘后 ${item.offset_minutes ?? 30} 分钟`);
  return item.time.slice(0, 5);
}

function describeSchedule(item: ScheduleDraft, t: Translate) {
  const day = item.repeat === "weekly" ? t(WEEK[item.weekday]) : "";
  if (item.repeat === "hourly") return `${t(MARKET[item.config.market])} · ${t("每小时")} :${item.time.slice(3, 5)}`;
  return `${t(MARKET[item.config.market])} · ${t(REPEAT[item.repeat])}${day ? ` ${day}` : ""} ${describeTiming(item, t)} · ${t("市场当地时间")}`;
}

function NextRun({ item, suspended = false }: { item: Schedule; suspended?: boolean }) {
  const t = useT();
  if (!item.enabled) return <small>{t("计划已暂停")}</small>;
  if (suspended) return <small>{t("自动调度暂停 · 可立刻运行")}</small>;
  if (!item.next_run) return <small>{t("等待交易日历确认 · 自动重试")}</small>;
  const value = new Date(item.next_run).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai",
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  return <small className="schedule-next-run">{t("下次执行")}<time dateTime={item.next_run}>{t(value)}</time> <span>{t("北京时间")}</span></small>;
}

function ScheduleHistory({ id, onTask }: { id: string; onTask: (id: string) => void }) {
  const t = useT();
  const history = useResearchList<Task>(`schedules/${id}/history`, "tasks");
  return <div className="schedule-history">
    <h3>{t("任务历史")}</h3>
    {history.error && <p role="alert">{t(history.error)}</p>}
    {!history.error && !history.items.length && <p>{t(history.loading ? "正在读取执行记录…" : "还没有执行记录，可点击「立刻运行」试跑。")}</p>}
    {history.items.map(task => <article key={task.id} className="workbench-task-row">
      <div><strong>{t(displayTime(task.created_at))}</strong>
        <small>{t(task.trigger === "manual" ? "手动试跑" : task.trigger === "clock" ? "到点执行" : "历史执行")} · {t(statusLabels[task.status] ?? task.status)}</small>
        {(task.summary || task.error) && <p>{t(task.summary || task.error)}</p>}
      </div>
      <button className="chat-config-toggle" onClick={() => onTask(task.id)}>{t(task.report_id ? "查看执行与报告" : "查看执行进度")}</button>
    </article>)}
  </div>;
}

export function SchedulePanel({ config, onTask, historyId, setHistoryId, candidates }: {
  config: ResearchConfig; onTask: (id: string) => void;
  historyId: string | null; setHistoryId: (id: string | null) => void;
  candidates: ReturnType<typeof import("./review-candidates").useReviewCandidates>;
}) {
  const t = useT();
  const schedules = useResearchList<Schedule, { scheduler_enabled: boolean }>("schedules", "schedules");
  const [draft, setDraft] = useState<ScheduleDraft | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState<{ scheduleId: string; id: string; message: string } | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);
  const deletion = useDeletion(async paths => {
    if (historyId && paths.includes(`schedules/${historyId}`)) setHistoryId(null);
    if (editing && paths.includes(`schedules/${editing}`)) { setEditing(null); setDraft(null); }
    if (submitted && paths.includes(`schedules/${submitted.scheduleId}`)) setSubmitted(null);
    await schedules.refresh();
  });
  const actionPending = toggling !== null || saving || submitting !== null;
  const visibleSchedules = schedules.items.filter(item =>
    `${item.name} ${item.config.symbol}`.toLowerCase().includes(search.toLowerCase()),
  );
  const form = useRef<HTMLFormElement>(null);
  const draftOpen = draft !== null;
  const draftMarket = draft?.config.market;
  const stockDraft = draft?.workflow === "stock";
  const mixedMainland = draft && ["morning", "watch", "weekly"].includes(draft.workflow);
  const availableCandidates = candidates.items.filter(item => mixedMainland || item.symbol.endsWith(`.${draftMarket}`));
  const draftedCodes = new Set(draft?.symbols.map(symbol => symbol.trim().toUpperCase()).filter(Boolean));
  useEffect(() => {
    if (draftOpen) form.current?.scrollIntoView({ block: "start" });
  }, [draftOpen]);
  function open(preset?: typeof presets[number]) {
    const market = preset?.market ?? config.market;
    const workflow = preset?.workflow ?? "stock";
    setEditing(null);
    setError("");
    setDraft({
      name: preset ? t(preset.name) : "", time: preset?.time ?? "09:00", repeat: preset?.repeat ?? "weekdays",
      weekday: preset?.weekday ?? 0, enabled: true,
      timing: preset?.timing ?? "clock", offset_minutes: preset?.offset_minutes ?? 30,
      workflow, symbols: [], keyword: "", window_hours: preset?.repeat === "hourly" ? 1 : 24, move_threshold: 3,
      config: {
        ...config, market,
        symbol: market === config.market ? config.symbol : BENCHMARK[market],
        benchmark: BENCHMARK[market], peers: market === config.market ? config.peers : [],
        question: config.question,
      },
    });
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!draft || saving) return;
    const form = new FormData(event.currentTarget as HTMLFormElement);
    const time = draft.repeat === "hourly" ? draft.time : String(form.get("schedule_time") || draft.time);
    setSaving(true);
    setError("");
    try {
      const payload = draft.workflow === "stock" ? { ...draft, time } : {
        ...draft,
        time,
        symbols: draft.workflow === "news" ? [] : draft.symbols.map(symbol => symbol.trim()).filter(Boolean),
        config: { ...draft.config, symbol: BENCHMARK[draft.config.market], question: WORKFLOWS[draft.workflow][1] },
      };
      await researchRequest(editing ? `schedules/${editing}` : "schedules", editing ? "PUT" : "POST", payload);
      setDraft(null);
      await schedules.refresh();
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  }
  async function toggle(item: Schedule) {
    setToggling(item.id);
    setError("");
    try {
      await researchRequest(`schedules/${item.id}`, "PUT", { ...item, enabled: !item.enabled });
      await schedules.refresh();
    } catch (err) { setError(String(err)); }
    finally { setToggling(null); }
  }
  async function runNow(item: Schedule) {
    setSubmitting(item.id);
    setError("");
    setSubmitted(null);
    try {
      const result = await researchRequest<{ id: string; existing: boolean }>(`schedules/${item.id}/run`, "POST", {});
      setSubmitted({
        scheduleId: item.id,
        id: result.id,
        message: result.existing ? `「${item.name}」已有一次执行在排队或运行。` : `「${item.name}」已提交执行。`,
      });
      setHistoryId(item.id);
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(null);
    }
  }
  return <div className="workbench-page">
    <div className="workbench-title"><div><span className="section-eyebrow">SCHEDULES</span><h1>{t("定时任务")}</h1><p className="intro">{t("按市场当地时间自动运行研究，结果进入报告库和任务中心。")}</p></div>
      <button className="primary-button" onClick={() => open()}><Plus size={16} />{t("新建任务")}</button></div>
    {schedules.metadata?.scheduler_enabled === false && <p role="status" className="finance-card">
      {t("自动调度暂已暂停。计划设置会保留；仍可点击「立刻运行」手动试跑。")}
    </p>}
    {(error || schedules.error) && <p role="alert" className="error-banner">{t(error || schedules.error)}</p>}
    {draft && <form ref={form} className="finance-card workbench-form" onSubmit={save}>
      <h2>{t(editing ? "编辑定时任务" : "新建定时任务")}</h2>
      <label>{t("任务名称")}<input required maxLength={30} value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} /></label>
      <label>{t("业务类型")}<select value={draft.workflow} onChange={e => setDraft({ ...draft, workflow: e.target.value as Workflow, symbols: [], keyword: "" })}>
        {Object.entries(WORKFLOWS).map(([key, info]) => <option key={key} value={key}>{t(info[0])}</option>)}
      </select></label>
      <p className="field-note">{t(WORKFLOWS[draft.workflow][1])}</p>
      {draft.workflow === "stock" && <label>{t("执行指令")}<textarea required rows={4} maxLength={2000} value={t(draft.config.question)}
        onChange={e => setDraft({ ...draft, config: { ...draft.config, question: e.target.value } })} /></label>}
      <div className="form-grid">
        <label>{t("市场")}<select value={draft.config.market} onChange={e => {
          const market = e.target.value as ResearchConfig["market"];
          setDraft({ ...draft, symbols: [], keyword: "",
            offset_minutes: draft.timing === "after_close" ? Math.max(draft.offset_minutes ?? 30, market === "SG" ? 20 : 15) : draft.offset_minutes,
            config: { ...draft.config, market, symbol: BENCHMARK[market], benchmark: BENCHMARK[market], peers: [] } });
        }}>{Object.entries(MARKET).map(([key, name]) => <option key={key} value={key}>{t(name)}</option>)}</select></label>
        {draft.workflow === "stock" && <label>{t("证券代码")}<input required value={draft.config.symbol} onChange={e => setDraft({ ...draft, config: { ...draft.config, symbol: e.target.value.toUpperCase() } })} /></label>}
        {draft.workflow !== "stock" && draft.workflow !== "news" && <label className="schedule-symbols">{t(draft.workflow === "morning" ? "代表标的（选填）" : "自选标的（最多 8 个）")}
          <input required={draft.workflow !== "morning"} value={draft.symbols.join(",")} placeholder={t(draft.workflow === "morning" ? "留空使用该市场的默认篮子" : BENCHMARK[draft.config.market])}
            onChange={e => setDraft({ ...draft, symbols: e.target.value.toUpperCase().split(/[,，]/) })} /></label>}
        {["morning", "news"].includes(draft.workflow) && <label>{t("新闻关键词")}<input value={draft.keyword} maxLength={80} placeholder={t("留空使用市场主题")}
          onChange={e => setDraft({ ...draft, keyword: e.target.value })} /></label>}
        {["morning", "news", "filings"].includes(draft.workflow) && <label>{t("回看小时数")}<input type="number" required min={1} max={168} value={draft.window_hours}
          onChange={e => setDraft({ ...draft, window_hours: Number(e.target.value) })} /></label>}
        {draft.workflow === "watch" && <label>{t("涨跌幅阈值（%）")}<input type="number" required min={0.1} max={30} step={0.1} value={draft.move_threshold}
          onChange={e => setDraft({ ...draft, move_threshold: Number(e.target.value) })} /></label>}
        <label>{t("重复")}<select value={draft.repeat} onChange={e => setDraft({ ...draft, repeat: e.target.value as ScheduleDraft["repeat"],
          timing: e.target.value === "trading_days" ? draft.timing : "clock" })}>
          {Object.entries(REPEAT).map(([key, value]) => <option key={key} value={key}>{t(value)}</option>)}
        </select></label>
        {draft.repeat === "trading_days" && <label>{t("执行时点")}<select value={draft.timing ?? "clock"} onChange={e => {
          const timing = e.target.value as ScheduleDraft["timing"];
          setDraft({ ...draft, timing, offset_minutes: timing === "after_close"
            ? Math.max(draft.offset_minutes ?? 30, draft.config.market === "SG" ? 20 : 15) : draft.offset_minutes ?? 30 });
        }}>
          <option value="clock">{t("固定时间")}</option><option value="before_open">{t("开盘前")}</option><option value="after_close">{t("收盘后")}</option>
        </select></label>}
        {t(draft.repeat === "hourly" ? <label>{t("每小时第几分钟")}<input required type="number" min={0} max={59} value={Number(draft.time.slice(3, 5))}
          onChange={e => setDraft({ ...draft, time: `00:${e.target.value.padStart(2, "0")}` })} /></label>
          : draft.repeat === "trading_days" && draft.timing && draft.timing !== "clock"
            ? <label>{t(draft.timing === "before_open" ? "提前分钟数" : "延后分钟数")}<input required type="number"
                min={draft.timing === "before_open" ? 0 : draft.config.market === "SG" ? 20 : 15} max={180}
                value={draft.offset_minutes ?? 30} onChange={e => setDraft({ ...draft, offset_minutes: Number(e.target.value) })} /></label>
            : <label>{t("当地执行时间")}<input name="schedule_time" required type="time" value={draft.time.slice(0, 5)} onChange={e => setDraft({ ...draft, time: e.target.value })} /></label>)}
        {draft.repeat === "weekly" && <label>{t("星期")}<select value={draft.weekday} onChange={e => setDraft({ ...draft, weekday: Number(e.target.value) })}>
          {WEEK.map((day, index) => <option key={day} value={index}>{t(day)}</option>)}
        </select></label>}
      </div>
      {draft.workflow !== "news" && (draftMarket === "SH" || draftMarket === "SZ") &&
        <details className="schedule-candidates">
          <summary>{t("从研究候选池选取标的")}</summary>
          <p className="field-note">{t(stockDraft ? "选择一个标的填入证券代码。" : "将候选添加到当前标的列表，可以继续手动编辑。")}
            {t(mixedMainland ? "可选沪深两市标的。" : "仅显示所选市场的标的。")}{t("保存后的计划会保留本次选择。")}</p>
          {candidates.error && <div className="candidate-error">{t("候选池读取失败。")}<button type="button" className="chat-config-toggle" onClick={() => void candidates.refresh()}>{t("重试读取")}</button>
          </div>}
          {!availableCandidates.length && !candidates.error && <p role={candidates.loading ? "status" : undefined} className="muted">
            {t(candidates.loading ? "正在读取候选池…" : "当前市场暂无可用候选。")}
          </p>}
          {!!availableCandidates.length && <div className="schedule-candidate-options">
            {availableCandidates.map(({ symbol }) => {
              const selected = stockDraft ? draft.config.symbol === symbol : draftedCodes.has(symbol);
              return <button type="button" className="chat-config-toggle" key={symbol}
                disabled={selected || saving || (!stockDraft && draftedCodes.size >= 8)}
                aria-label={t(`${selected ? "已选" : "选取"} ${symbol}`)}
                onClick={() => setDraft(stockDraft ? { ...draft, config: { ...draft.config, symbol } }
                  : { ...draft, symbols: [...draft.symbols.filter(value => value.trim()), symbol] })}>
                {t(selected ? "✓ " : "+ ")}{t(symbol)}
              </button>;
            })}
          </div>}
          {!stockDraft && draftedCodes.size >= 8 && <p className="field-note">{t("已达到 8 个标的。移除一个后可以继续添加。")}</p>}
        </details>}
      <p className="field-note">{t("美股用纽约时间，其他市场用 UTC+8。执行时使用市场当地当天作为截止日。任务在本机服务运行时执行。")}</p>
      {draft.repeat === "trading_days" && <p className="field-note">{t("按交易所日历执行，休市日跳过。")}{t(draft.timing && draft.timing !== "clock"
        ? "开盘按股票日间交易起点计算，半日市使用提前收盘时点，美股自动跟随夏令时。为等待收市流程及数据，收盘后至少延后 15 分钟，新加坡至少 20 分钟。"
        : "半日市仍按所选固定时间运行。")}{t("日历待确认时暂缓执行。已安排的任务超过 15 分钟后跳过，可随时手动试跑。")}</p>}
      {draft.repeat === "weekdays" && <p className="field-note">{t("周一至周五均执行，包括交易所节假日。")}</p>}
      {["SH", "SZ"].includes(draft.config.market) && ["morning", "watch", "weekly"].includes(draft.workflow) &&
        <p className="field-note">{t("可同时填写 .SH 和 .SZ 标的。行情按同一组交易日比较，北京时间 15:15 后运行可纳入当天收盘。缺少对应日线的标的会单独标明。")}</p>}
      <div className="workbench-actions"><button type="button" className="chat-config-toggle" disabled={saving} onClick={() => { setDraft(null); setError(""); }}>{t("取消")}</button>
        <button className="primary-button" disabled={saving}>{t(saving ? "保存中…" : editing ? "保存计划" : "创建")}</button></div>
    </form>}
    <h2>{t("我的任务")}</h2>
    <input className="workbench-search" aria-label={t("搜索定时任务")} placeholder={t("搜索任务名称或证券")} value={search}
      disabled={deletion.busy} onChange={e => { deletion.reset(); setSearch(e.target.value); }} />
    <div className="workbench-grid">
      {visibleSchedules.map(item =>
        <article className="finance-card workbench-item" key={item.id}>
          <div className="workbench-item-head"><div className="workbench-select-item">
            <input type="checkbox" aria-label={t(`选择 ${item.name}`)} disabled={deletion.busy}
              checked={deletion.selected.includes(`schedules/${item.id}`)} onChange={() => deletion.toggle(`schedules/${item.id}`)} />
            <h3>{t(item.name)}</h3></div>
            <label className="schedule-switch"><span>{t(item.enabled ? "已启用" : "已暂停")}</span>
              <input type="checkbox" role="switch" aria-label={t(`启用 ${item.name} 的自动执行`)} checked={item.enabled}
                disabled={toggling !== null} onChange={() => void toggle(item)} />
            </label></div>
          <p>{t(WORKFLOWS[item.workflow ?? "stock"][0])} · {t(describeSchedule(item, t))}</p>
          <p>{t(item.workflow === "stock" ? item.config.symbol : item.symbols?.join("、") || item.keyword || "市场主题")}</p>
          <NextRun item={item} suspended={schedules.metadata?.scheduler_enabled === false} />
          <div className="workbench-actions">
            <button className="primary-button" disabled={submitting !== null} onClick={() => void runNow(item)}>
              <Play size={14} />{t(submitting === item.id ? "提交中…" : "立刻运行")}
            </button>
            <button className="chat-config-toggle" onClick={() => { setError(""); setEditing(item.id); setDraft(item); }}>{t("编辑")}</button>
            <button className="chat-config-toggle" aria-expanded={historyId === item.id} onClick={() => setHistoryId(historyId === item.id ? null : item.id)}>
              {t(historyId === item.id ? "收起历史" : "任务历史")}
            </button>
            <button className="chat-config-toggle danger-button" aria-label={t(`删除 ${item.name}`)} aria-expanded={deletion.target?.anchor === item.id}
              disabled={deletion.busy} onClick={() => deletion.request(item.id, [{ path: `schedules/${item.id}`, name: item.name }])}>
              <Trash2 size={14} />{t("删除")}</button>
          </div>
          <DeleteConfirmation deletion={deletion} anchor={item.id} plans blocked={actionPending} />
          {submitted?.scheduleId === item.id && <div className="workbench-actions">
            <small role="status">{t(submitted.message)}</small>
            <button className="chat-config-toggle" onClick={() => onTask(submitted.id)}>{t("查看执行进度")}</button>
          </div>}
          {historyId === item.id && <ScheduleHistory key={submitted?.scheduleId === item.id ? submitted.id : item.id} id={item.id} onTask={onTask} />}
        </article>)}
      {!visibleSchedules.length && <p className="muted">{t(schedules.loading ? "正在加载…" : search ? "没有匹配的定时任务。" : "还没有定时任务。")}</p>}
    </div>
    <DeleteSelection deletion={deletion} plans blocked={actionPending}
      items={visibleSchedules.map(item => ({ path: `schedules/${item.id}`, name: item.name }))} />
    <h2>{t("从预设开始")}</h2><p className="intro">{t("选择预设会填好草稿。检查并点击「创建」后才启用计划。")}</p>
    <div className="workbench-grid">{presets.map(preset =>
      <button type="button" className="finance-card workbench-preset" key={preset.name} onClick={() => open(preset)}>
        <CalendarClock size={20} /><span><strong>{t(preset.name)}</strong><small>{t(MARKET[preset.market])} · {t(REPEAT[preset.repeat])} · {t(preset.repeat === "hourly" ? "第 5 分钟" : describeTiming(preset, t))}</small></span><Plus size={17} />
      </button>)}</div>
  </div>;
}

export function TaskPanel({ onReport, onTask, onSchedules }: {
  onReport: (id: string) => void; onTask: (id: string) => void; onSchedules: () => void;
}) {
  const t = useT();
  const tasks = useResearchList<Task>("tasks", "tasks");
  const schedules = useResearchList<Schedule, { scheduler_enabled: boolean }>("schedules", "schedules");
  const [view, setView] = useState<"runs" | "plans">("runs");
  const [filter, setFilter] = useState("all");
  const [kind, setKind] = useState("all");
  const deletion = useDeletion(async paths => {
    await (paths[0].startsWith("schedules/") ? schedules : tasks).refresh();
  });
  const shown = tasks.items.filter(task =>
    (filter === "all" || task.status === filter) && (kind === "all" || task.kind === kind),
  );
  return <div className="workbench-page">
    <span className="section-eyebrow">ACTIVITY</span><h1><ClipboardList size={24} />{t("任务中心")}</h1>
    <p className="intro">{t("查看手动研究、定时计划和每一次定时执行的结果。")}</p>
    <div className="task-view-switch" role="group" aria-label={t("任务中心视图")}>
      <button type="button" aria-pressed={view === "runs"} disabled={deletion.busy} onClick={() => { deletion.reset(); setView("runs"); }}>
        <ClipboardList size={16} />{t("执行记录")}<span>{t(tasks.loading ? "…" : tasks.items.length)}</span>
      </button>
      <button type="button" aria-pressed={view === "plans"} disabled={deletion.busy} onClick={() => { deletion.reset(); setView("plans"); }}>
        <CalendarClock size={16} />{t("定时计划")}<span>{t(schedules.loading ? "…" : schedules.items.length)}</span>
      </button>
    </div>
    {(tasks.error || schedules.error) && <p className="error-banner" role="alert">{t(tasks.error || schedules.error)}</p>}
    {view === "runs" && <section className="finance-card">
      <div className="workbench-item-head task-filter-head"><h2>{t("执行记录")}</h2>
        <div className="task-filters">
        <select aria-label={t("筛选任务类型")} value={kind} disabled={deletion.busy} onChange={e => { deletion.reset(); setKind(e.target.value); }}>
          <option value="all">{t("全部类型")}</option><option value="manual">{t("单股分析")}</option><option value="scheduled">{t("定时执行")}</option><option value="document">{t("资料处理")}</option><option value="knowledge">{t("知识任务")}</option>
        </select>
        <select aria-label={t("筛选任务状态")} value={filter} disabled={deletion.busy} onChange={e => { deletion.reset(); setFilter(e.target.value); }}>
          <option value="all">{t("全部状态")}</option>{Object.entries(statusLabels).filter(([key]) => key !== "pending").map(([key, label]) => <option key={key} value={key}>{t(label)}</option>)}
        </select></div></div>
      {!shown.length && <p className="muted">{t(tasks.loading ? "正在加载…" : "没有匹配的执行记录。")}</p>}
      {shown.map(task => <article key={task.id}><div className="workbench-task-row">
        <input type="checkbox" aria-label={t(`选择 ${task.name} · ${displayTime(task.created_at)}`)}
          disabled={deletion.busy || !canDeleteTask(task.status)}
          checked={deletion.selected.includes(`tasks/${task.id}`)} onChange={() => deletion.toggle(`tasks/${task.id}`)} />
        <div><strong>{t(task.name)}</strong><small>{t(task.kind === "knowledge" ? "知识任务" : task.kind === "document" ? "资料处理" : task.kind === "scheduled" ? "定时执行" : "单股分析")} · {t(displayTime(task.created_at))}</small>{task.error && <p className="muted">{t(task.error)}</p>}</div>
        <span className={`status-badge ${task.status}`}>{t(statusLabels[task.status] ?? task.status)}</span>
        <button className="chat-config-toggle" onClick={() => onTask(task.id)}>{t("查看任务")}</button>
        {task.report_id && <button className="chat-config-toggle" onClick={() => onReport(task.report_id!)}>{t("查看报告")}<ArrowUpRight size={14} /></button>}
        <button className="chat-config-toggle danger-button" disabled={deletion.busy || !canDeleteTask(task.status)}
          aria-expanded={deletion.target?.anchor === task.id} title={t(!canDeleteTask(task.status) ? "执行结束后可删除" : undefined)}
          onClick={() => deletion.request(task.id, [{ path: `tasks/${task.id}`, name: task.name }])}>
          <Trash2 size={14} />{t("删除")}</button>
      </div><DeleteConfirmation deletion={deletion} anchor={task.id} plans={false} /></article>)}
      <DeleteSelection deletion={deletion} plans={false}
        items={shown.filter(task => canDeleteTask(task.status)).map(task => ({ path: `tasks/${task.id}`, name: task.name }))} />
    </section>}
    {view === "plans" && <section className="finance-card"><div className="workbench-item-head"><h2>{t("定时计划")}</h2><button className="chat-config-toggle" onClick={onSchedules}>{t("管理计划")}</button></div>
      {!schedules.items.length && <p className="muted">{t(schedules.loading ? "正在加载…" : "还没有定时计划。")}</p>}
      {schedules.items.map(item => <article key={item.id}><div className="workbench-task-row">
        <input type="checkbox" aria-label={t(`选择 ${item.name}`)} disabled={deletion.busy}
          checked={deletion.selected.includes(`schedules/${item.id}`)} onChange={() => deletion.toggle(`schedules/${item.id}`)} />
        <div><strong>{t(item.name)}</strong><small>{t(describeSchedule(item, t))}</small><NextRun item={item} suspended={schedules.metadata?.scheduler_enabled === false} /></div>
        <span className="status-badge">{t(!item.enabled || schedules.metadata?.scheduler_enabled === false ? "已暂停" : item.next_run ? "等待下次执行" : "待确认")}</span>
        <button className="chat-config-toggle danger-button" disabled={deletion.busy} aria-expanded={deletion.target?.anchor === item.id}
          onClick={() => deletion.request(item.id, [{ path: `schedules/${item.id}`, name: item.name }])}>
          <Trash2 size={14} />{t("删除")}</button>
      </div><DeleteConfirmation deletion={deletion} anchor={item.id} plans /></article>)}
      <DeleteSelection deletion={deletion} plans
        items={schedules.items.map(item => ({ path: `schedules/${item.id}`, name: item.name }))} />
    </section>}
  </div>;
}

type Settings = { data: { cache_minutes: number }; cli_available: boolean };

export function SettingsPanel({ section }: { section: "data" | "ai" }) {
  return section === "ai" ? <><AISettingsPanel /><div className="workbench-page"><EmbeddingSettingsPanel /></div></> : <DataSettingsPanel />;
}

function DataSettingsPanel() {
  const t = useT();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    researchRequest<Settings>("settings", "GET", undefined, controller.signal).then(setSettings).catch(err => { if (!controller.signal.aborted) setError(String(err)); });
    return () => controller.abort();
  }, []);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!settings || saving) return;
    setSaving(true); setNotice(""); setError("");
    try { await researchRequest("settings/data", "PUT", settings.data); setNotice("设置已保存。"); }
    catch (err) { setError(String(err)); }
    finally { setSaving(false); }
  }
  return <div className="workbench-page">
    <span className="section-eyebrow">PREFERENCES</span><h1>{t("数据源设置")}</h1>
    {error && <p className="error-banner" role="alert">{t(error)}</p>}
    {!settings && !error && <p className="muted">{t("正在读取设置…")}</p>}
    {settings && <form className="finance-card workbench-form" onSubmit={save}>
      <div className="section-title"><Database size={18} /><h2>Longbridge CLI</h2><span>{t(settings.cli_available ? "已找到 CLI" : "未找到 CLI")}</span></div>
      <p className="muted">{t("当前研究使用 Longbridge 提供行情、新闻和公告。数据权限由本机 CLI 授权决定。")}</p>
      <label>{t("缓存有效期（分钟）")}<input required type="number" min={0} max={120} value={settings.data.cache_minutes}
        onChange={e => setSettings({ ...settings, data: { cache_minutes: Number(e.target.value) } })} /></label>
      <p className="field-note">{t("设为 0 时，每次查询都会请求数据源。")}</p>
      <div className="workbench-actions"><span role="status">{t(notice)}</span><button className="primary-button" disabled={saving}>{t(saving ? "保存中…" : "保存设置")}</button></div>
    </form>}
  </div>;
}
