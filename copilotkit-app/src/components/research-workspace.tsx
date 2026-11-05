"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { Activity, Bot, CalendarClock, ClipboardList, Database, MessageSquare, Plus, ArrowUpRight, Check, ChevronDown, ChevronRight, Download, ExternalLink, FileText, FlaskConical, Layers3, LoaderCircle, Play, Settings2, ShieldCheck, Square, X, Sun, Moon } from "lucide-react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { z } from "zod";
import { CopilotChat, CopilotChatView, type CopilotChatViewProps, CopilotThreadsDrawer, useAgent, useCopilotChatConfiguration, useFrontendTool, useHumanInTheLoop } from "@copilotkit/react-core/v2";
import { SchedulePanel, TaskPanel, SettingsPanel, researchRequest, useResearchList } from "@/components/workbench-panels";
import { ResearchTask, ReportQA } from "@/components/research-task";
import { cachedResearchHistory, readResearchHistory } from "@/lib/research-history";
import { FollowupContext, useFollowupView } from "@/components/chat-followups";
import { MarketReview } from "@/components/market-review";
import { CandidateButton, useReviewCandidates } from "@/components/review-candidates";
import { ReportLibrary } from "@/components/report-library";
import { ReportComparison } from "@/components/report-comparison";
import { CitationText } from "@/components/research-citation";
import type { CheckSeed } from "@/components/review-checks";
import { AShareEvents, canPreviewAEvents } from "@/components/a-share-events";
import { useGenerativeUIExamples } from "@/hooks";
import { useTheme } from "@/hooks/use-theme";
import { ANALYSTS, DEFAULT_CONFIG, formatReportTime, ResearchConfig, Report, ReportSummary, STAGE_NAMES, STATUS_NAMES } from "@/lib/research";

type Tab = "free" | "config" | "review" | "report" | "sources" | "library" | "comparison" | "schedules" | "tasks" | "execution" | "data" | "ai";
type RecentTask = { id: string; symbol: string; status: string; created_at: string; kind: string };
const safeUrl = (value: string) => /^https?:\/\//i.test(value) ? value : "#";
const mainlandCode = /^[0-9]{6}\.(SH|SZ)$/;
const eventSourceNames: Record<string, string> = { billboard: "龙虎榜", unlock: "限售解禁", holder_change: "股东增减持" };

const FREE_EXAMPLES = [
  { title: "看懂技术指标", prompt: "RSI、MACD 和均线分别能说明什么？它们有哪些局限？" },
  { title: "梳理研究思路", prompt: "研究一家上市公司时，应该先看哪些数据和公开资料？" },
  { title: "评估证据质量", prompt: "怎样区分财报中的事实、市场预期和分析师的判断？" },
];

const FreeChatDraft = createContext<((value: string) => void) | undefined>(undefined);

function FreeWelcome({ input }: { input: React.ReactElement }) {
  const onExample = useContext(FreeChatDraft);
  return <div className="free-welcome">
    <div className="free-welcome-content">
      <div className="free-welcome-icon"><Activity size={26} /></div>
      <h1>一起理清市场脉络。</h1>
      <p>从一个问题开始，读懂指标、梳理研究思路，或核对一条投资判断的依据。</p>
      <div className="free-welcome-examples">{FREE_EXAMPLES.map(example =>
        <button type="button" className="chat-config-toggle" key={example.title} onClick={() => onExample?.(example.prompt)}>{example.title}</button>
      )}</div>
      <small>示例会填入输入框，可以修改后再发送。</small>
    </div>
    <div className="free-welcome-input">{input}</div>
  </div>;
}

function FreeChatView(props: CopilotChatViewProps) {
  const followups = useFollowupView(props);
  return <FreeChatDraft.Provider value={props.onInputChange}>
    <CopilotChatView {...props} {...followups} welcomeScreen={FreeWelcome} />
  </FreeChatDraft.Provider>;
}

export function ResearchWorkspace() {
  const { theme, setTheme } = useTheme();
  const { agent, isReady } = useAgent();
  const chatConfiguration = useCopilotChatConfiguration();
  const threadId = chatConfiguration?.threadId;
  useGenerativeUIExamples();
  const [config, setConfig] = useState<ResearchConfig>(DEFAULT_CONFIG);
  const aShare = canPreviewAEvents(config.symbol, config.market);
  const [tab, setTab] = useState<Tab>("config");
  const candidates = useReviewCandidates(tab === "review" || tab === "report" || tab === "schedules");
  const [error, setError] = useState("");
  const library = useResearchList<ReportSummary>(tab === "library" ? "reports" : null, "reports");
  const [comparisonIds, setComparisonIds] = useState<[string, string] | null>(null);
  const [savedReport, setSavedReport] = useState<Report | null>(null);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [checkSeed, setCheckSeed] = useState<CheckSeed | null>(null);
  const [reportCondition, setReportCondition] = useState<{ id: string; index: number } | null>(null);
  const [provider, setProvider] = useState<{ cli_available: boolean; model: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [execution, setExecution] = useState<{ id: string; from: "schedules" | "tasks" } | null>(null);
  const [scheduleHistoryId, setScheduleHistoryId] = useState<string | null>(null);
  const [stockOpen, setStockOpen] = useState(false);
  const [singleOpen, setSingleOpen] = useState(false);
  const { items: recentTasks, refresh: refreshRecentTasks } = useResearchList<RecentTask>(
    stockOpen && singleOpen ? "tasks?kind=manual&limit=3" : null, "tasks",
  );
  const [qaReportId, setQaReportId] = useState<string | null>(null);
  const [historyRequest, setHistoryRequest] = useState<{ threadId: string } | null>(null);
  const [historyResult, setHistoryResult] = useState<{ request: { threadId: string }; error?: string; incomplete?: boolean; cached?: boolean } | null>(null);
  const selectedHistory = historyRequest?.threadId === threadId ? historyRequest : null;
  const historyLoading = !!historyRequest && (!selectedHistory || historyResult?.request !== selectedHistory);
  const historyError = historyResult?.request === selectedHistory ? historyResult?.error : undefined;
  const historyBlockingError = historyError && !historyResult?.cached;
  const running = agent.isRunning;
  const chatVisible = tab === "free";
  const report = savedReport || (agent.state?.research as Report | undefined);

  useEffect(() => {
    const stored = localStorage.getItem("aperture-research-config");
    if (stored) { try { const value = JSON.parse(stored); if (Array.isArray(value.analysts)) setConfig({ ...DEFAULT_CONFIG, ...value }); } catch { /* use defaults */ } }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refreshStatus() {
      try {
        const response = await fetch("/api/research/status", { signal: controller.signal, cache: "no-store" });
        if (response.ok) {
          const status = await response.json();
          if (!controller.signal.aborted) setProvider(status);
          return;
        }
      } catch {
        // The Python service can take longer to start than the UI.
      }
      if (!controller.signal.aborted) timer = setTimeout(refreshStatus, 3000);
    }
    void refreshStatus();
    return () => { controller.abort(); clearTimeout(timer); };
  }, []);
  useEffect(() => { setSavedReport(null); setSourceId(null); }, [threadId]);
  useEffect(() => {
    if (!selectedHistory || !isReady) return;
    const request = selectedHistory;
    const controller = new AbortController();
    if (agent.threadId !== request.threadId || agent.isRunning) return;
    const cached = cachedResearchHistory(request.threadId);
    if (cached) {
      agent.setMessages(cached.messages);
      agent.setState(cached.state);
      setHistoryResult({ request, incomplete: cached.incomplete });
    }
    const initialMessages = agent.messages;
    const subscription = agent.subscribe({ onRunInitialized: () => controller.abort() });
    async function restore() {
      try {
        const history = await readResearchHistory(request.threadId, controller.signal);
        if (controller.signal.aborted || agent.threadId !== request.threadId || agent.isRunning || agent.messages !== initialMessages) return;
        agent.setMessages(history.messages);
        agent.setState(history.state);
        setHistoryResult({ request, incomplete: history.incomplete });
      } catch (error) {
        if (!controller.signal.aborted) {
          setHistoryResult({ request, cached: !!cached, incomplete: cached?.incomplete, error: error instanceof Error ? error.message : "无法读取会话历史，请重试。" });
        }
      }
    }
    void restore();
    return () => { controller.abort(); subscription.unsubscribe(); };
  }, [agent, isReady, selectedHistory]);
  useEffect(() => {
    if (tab === "sources" && sourceId) document.getElementById(`source-${sourceId}`)?.scrollIntoView({ block: "center" });
  }, [tab, sourceId, report?.id]);
  useEffect(() => {
    if (tab === "report" && reportCondition && reportCondition.id === report?.id) {
      document.getElementById(`report-condition-${reportCondition.index}`)?.focus();
      setReportCondition(null);
    }
  }, [tab, report?.id, reportCondition]);
  const viewedRunningReport = savedReport?.status === "running" ? savedReport.id : null;
  useEffect(() => {
    if (!viewedRunningReport || (tab !== "report" && tab !== "sources")) return;
    let active = true;
    const timer = window.setInterval(async () => {
      try {
        const latest = await researchRequest<Report>(`reports/${viewedRunningReport}`);
        if (active) setSavedReport(current => current?.id === viewedRunningReport ? latest : current);
      } catch (error) {
        if (active) setError(String(error));
      }
    }, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [viewedRunningReport, tab]);
  const updateConfig = (next: ResearchConfig) => {
    setConfig(next);
    localStorage.setItem("aperture-research-config", JSON.stringify(next));
  };
  const showSource = (id: string) => { setSourceId(id); setTab("sources"); };
  useFrontendTool({ name: "showResearchTab", description: "切换用户的研究工作区视图，不改变研究内容。",
    parameters: z.object({ tab: z.enum(["config", "report", "sources", "library"]) }),
    handler: async ({ tab }) => { setTab(tab); return `已显示${tab}`; } });
  useHumanInTheLoop({ name: "confirmResearchScope", description: "在更改用户原先选择的研究范围前，让用户确认或拒绝。",
    parameters: z.object({ proposal: z.string() }), render: ({ args, respond, status }) =>
      <div className="scope-card"><ShieldCheck size={20} /><strong>确认研究范围</strong><p>{args.proposal}</p>
        {status === "executing" ? <div className="button-row"><button onClick={() => respond?.("用户同意此研究范围")}>同意</button><button onClick={() => respond?.("用户拒绝变更，请保留原范围")}>保留原范围</button></div> : <small>{status === "complete" ? "已收到用户决定" : "正在准备确认…"}</small>}</div> });

  async function startResearch(event?: React.FormEvent) {
    event?.preventDefault(); setError("");
    if (!config.symbol.trim() || !config.analysts.filter(a => config.include_sentiment || a !== "sentiment").length) { setError("请输入证券代码，并至少启用一位分析师。"); return; }
    if (busy) return;
    setBusy(true);
    try {
      const configured = { ...config, peers: config.peers.map(p => p.trim()).filter(Boolean) };
      const task = await researchRequest<{ id: string }>("tasks", "POST", configured);
      setJobId(task.id);
      void refreshRecentTasks();
    } catch (e) {
      setError(e instanceof Error ? e.message : "研究任务提交失败。");
    } finally {
      setBusy(false);
    }
  }
  async function loadReport(id: string) {
    try {
      const response = await fetch(`/api/research/reports/${id}`);
      if (response.status === 404) throw new Error("报告已归档或不存在。");
      if (!response.ok) throw new Error("报告读取失败");
      const loaded = await response.json(); setSavedReport(loaded); setTab("report");
    } catch (e) { setError(String(e)); }
  }
  function openCheckReport(id: string, index: number) {
    setError("");
    setReportCondition({ id, index });
    if (report?.id === id) setTab("report");
    else void loadReport(id);
  }
  async function archive(id: string) {
    const response = await fetch(`/api/research/reports/${id}`, { method: "DELETE" });
    if (!response.ok) throw new Error("归档失败，请稍后重试。");
    if (savedReport?.id === id) setSavedReport(null);
    if (comparisonIds?.includes(id)) setComparisonIds(null);
    await library.refresh();
  }

  function newConversation() {
    setHistoryRequest(null);
    setTab("free");
    chatConfiguration?.startNewThread();
  }

  function newResearch() {
    setError("");
    setJobId(null);
    setTab("config");
    document.getElementById("chat-research-config")?.scrollIntoView({ block: "start" });
  }

  return <div className="finance-shell">
    <aside className="workbench-rail">
    <nav className="workbench-sidebar" aria-label="工作台导航">
      <span className="section-eyebrow">工作台</span>
      <button aria-current={tab === "free" && !historyRequest ? "page" : undefined} onClick={newConversation}><MessageSquare size={17} />自由对话</button>
      <button aria-current={tab === "review" ? "page" : undefined} onClick={() => setTab("review")}><Layers3 size={17} />收盘复盘</button>
      <details className="workbench-nav-group" onToggle={event => setStockOpen(event.currentTarget.open)}>
        <summary><Activity size={17} />股票分析 <ChevronDown size={13} /></summary>
        <details className="workbench-nav-subgroup" onToggle={event => setSingleOpen(event.currentTarget.open)}>
          <summary>单股分析 <ChevronDown size={13} /></summary>
          <button aria-current={tab === "config" && !jobId ? "page" : undefined} onClick={newResearch}><Plus size={15} />新增任务</button>
          {recentTasks.map(task => <button key={task.id} aria-current={tab === "config" && jobId === task.id ? "page" : undefined}
            onClick={() => { setJobId(task.id); setTab("config"); }}>
            <span>{task.symbol}<time dateTime={task.created_at}>{formatReportTime(task.created_at)}</time></span><small>{task.status === "queued" ? "排队中" : STATUS_NAMES[task.status] ?? task.status}</small>
          </button>)}
        </details>
        <button aria-current={["library", "comparison", "report", "sources"].includes(tab) ? "page" : undefined} onClick={() => setTab("library")}>报告库</button>
      </details>
      <button aria-current={tab === "schedules" ? "page" : undefined} onClick={() => setTab("schedules")}><CalendarClock size={17} />定时任务</button>
      <button aria-current={tab === "tasks" ? "page" : undefined} onClick={() => setTab("tasks")}><ClipboardList size={17} />任务中心</button>
      <details className="workbench-nav-group">
        <summary><Settings2 size={17} />个人设置 <ChevronDown size={13} /></summary>
        <button aria-current={tab === "data" ? "page" : undefined} onClick={() => setTab("data")}><Database size={15} />数据源设置</button>
        <button aria-current={tab === "ai" ? "page" : undefined} onClick={() => setTab("ai")}><Bot size={15} aria-hidden="true" />AI 设置</button>
      </details>
    </nav>
      <div className="workbench-history">
    <CopilotThreadsDrawer agentId="default" collapsible={false} label="研究会话" recentLabel="最近对话" onThreadSelect={id => {
      setTab("free");
      if (id !== threadId) {
        setHistoryRequest({ threadId: id });
        // Explicit mode connects to a live run. A sidebar selection only loads saved events.
        chatConfiguration?.setActiveThreadId(id, { explicit: false });
      }
    }} onNewThread={newConversation} />
      </div>
    </aside>
    <div className="finance-app">
      <header className="finance-header">
        <div className="finance-brand"><span className="brand-orbit">a</span><div><strong>APERTURE<span> RESEARCH</span></strong><small>让每一个判断，都有据可循。</small></div></div>
        <div className="header-actions"><span className="provider-badge"><i className={provider?.cli_available ? "online" : ""} />{provider?.cli_available ? "Longbridge CLI 就绪" : "等待研究服务"}</span><button className="theme-toggle" aria-label={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"} title={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}</button><a href="https://dashboard.operations.copilotkit.ai" target="_blank" rel="noreferrer">运行后台 <ArrowUpRight size={14} /></a><a href="/playground" title="保留的 CopilotKit 原生功能示例"><FlaskConical size={18} /></a></div>
      </header>
      {(tab === "report" || tab === "sources") && <nav className="research-nav report-navigation" aria-label="报告导航">
        {execution?.id === report?.id && execution && <button onClick={() => setTab("execution")}>返回执行</button>}
        <button onClick={() => setTab("library")}>报告库</button>
        {report && comparisonIds?.includes(report.id) && <button onClick={() => setTab("comparison")}>返回报告对照</button>}
        <button className={tab === "report" ? "active" : ""} onClick={() => setTab("report")}>分析报告</button>
        <button className={tab === "sources" ? "active" : ""} onClick={() => setTab("sources")}>来源与证据</button>
      </nav>}
      {error && <div role="alert" className="error-banner">{error}<button aria-label="关闭提示" onClick={() => setError("")}><X size={15} /></button></div>}
      <main className="finance-content">
        <section className="native-chat-panel chat-first-panel" aria-label="研究对话" hidden={!chatVisible}>
          {(historyLoading || historyBlockingError) && <div className="chat-history-placeholder">
            {historyLoading
              ? <p role="status"><LoaderCircle aria-hidden="true" size={18} className="spin" />正在打开历史对话…</p>
              : <><p role="alert">{historyError}</p>
                <button className="chat-config-toggle" onClick={() => threadId && setHistoryRequest({ threadId })}>重试</button></>}
          </div>}
          {historyError && !historyBlockingError && <p role="status" className="chat-research-toolbar">
            {historyError} 当前显示上次读取的历史。
            <button className="chat-config-toggle" onClick={() => threadId && setHistoryRequest({ threadId })}>重试</button>
          </p>}
          {historyResult?.request === selectedHistory && historyResult?.incomplete && !running &&
            <p className="chat-research-toolbar">部分历史工具结果未保存。工具卡上的「Running」是当时的状态。</p>}
          <div className="chat-history-body" hidden={historyLoading || !!historyBlockingError}>
            <FollowupContext.Provider value={{ agent, threadId }}>
              <CopilotChat key={threadId} attachments={{ enabled: true }} chatView={FreeChatView} labels={{ welcomeMessageText: "一起理清市场脉络。", chatInputPlaceholder: "问一个市场、公司或研究方法的问题…", chatDisclaimerText: "请结合原始来源核对结论。" }} />
            </FollowupContext.Provider>
          </div>
        </section>
        <div className="research-scroll" hidden={tab !== "review"}><MarketReview visible={tab === "review"} candidates={candidates}
          checkSeed={checkSeed} onCheckSeed={setCheckSeed}
          onDismissCheck={seed => setCheckSeed(current => current === seed ? null : current)} onOpenReport={openCheckReport}
          onOpenCandidateReport={id => { setError(""); setReportCondition(null); void loadReport(id); }}
          onResearch={(symbol, session, benchmark) => {
          const market = symbol.endsWith(".SH") ? "SH" : "SZ";
          updateConfig({ ...config, symbol, market, as_of: session, benchmark, peers: [] });
          newResearch();
        }} /></div>
        <div className="research-scroll" hidden={tab !== "library"}>
          <ReportLibrary reports={library.items} loading={library.loading} error={library.error} refresh={library.refresh}
            onOpen={loadReport} onArchive={archive} onNew={() => setTab("config")}
            onCompare={ids => { setComparisonIds(ids); setTab("comparison"); }} />
        </div>
        {comparisonIds && <div className="research-scroll" hidden={tab !== "comparison"} key={comparisonIds.join(":")}>
            <ReportComparison ids={comparisonIds} visible={tab === "comparison"} onBack={() => setTab("library")}
              onOpen={loadReport} onSource={(selected, id) => { setSavedReport(selected); showSource(id); }} />
        </div>}
        {!chatVisible && tab !== "review" && tab !== "library" && tab !== "comparison" && <div className="research-scroll" key={tab}>
            {tab === "config" && <div className="stock-workspace">
              <span className="section-eyebrow">股票分析</span>
              <h1>单股分析</h1>
              <p className="intro">选择标的和研究范围，提交后可在此跟踪进度。</p>
              <form id="chat-research-config" onSubmit={startResearch} className="research-form stock-research-form">
              <fieldset disabled={busy}>
                <section className="finance-card"><div className="section-title"><Activity size={18} /><h2>研究标的</h2><span>必填</span></div>
                  <div className="form-grid"><label>证券代码<input required maxLength={22} value={config.symbol} onChange={e => updateConfig({ ...config, symbol: e.target.value.toUpperCase() })} placeholder="1211.HK" /></label>
                    <label>市场<select value={config.market} onChange={e => { const market = e.target.value as ResearchConfig["market"]; updateConfig({ ...config, market, symbol: "", benchmark: market === "US" ? "SPY.US" : market === "HK" ? "2800.HK" : market === "SG" ? "ES3.SG" : "510300.SH", peers: [] }); }}><option value="HK">HK · 香港</option><option value="US">US · 美国</option><option value="SH">SH · 沪市</option><option value="SZ">SZ · 深市</option><option value="SG">SG · 新加坡</option></select></label>
                    <label>信息截止日期<input required type="date" min="2000-01-01" max={new Date().toLocaleDateString("sv-SE")} value={config.as_of}
                      onInput={e => updateConfig({ ...config, as_of: e.currentTarget.value })} /></label>
                    <label>研究深度<select value={config.depth} onChange={e => updateConfig({ ...config, depth: e.target.value as ResearchConfig["depth"] })}><option value="quick">快速 · 专项分析</option><option value="standard">标准 · 多空交叉审查</option><option value="deep">深度 · 更多证据与多空审查</option></select></label></div>
                  <label className="question-label">研究问题<textarea rows={3} value={config.question} maxLength={2000} onChange={e => updateConfig({ ...config, question: e.target.value })} /></label>
                  <p className="field-note">非交易日使用此前最近交易日。发布时间不明或晚于截止日的数据会被排除。</p></section>
                {aShare && <AShareEvents key={`${aShare}:${config.as_of}`} symbol={aShare} asOf={config.as_of} />}
                <details className="chat-config-advanced" open><summary>分析师与分析选项</summary>
                <section className="finance-card"><div className="section-title"><Layers3 size={18} /><h2>分析师团队</h2><span>{config.analysts.length} 位已选</span></div>
                  <div className="analyst-grid">{ANALYSTS.map(a => { const selected = config.analysts.includes(a.id); return <button type="button" key={a.id} aria-pressed={selected} className={`analyst-card ${selected ? "selected" : ""}`} onClick={() => updateConfig({ ...config, analysts: selected ? config.analysts.filter(v => v !== a.id) : [...config.analysts, a.id] })}><span className="analyst-icon">{a.icon}</span><span><strong>{a.name}</strong><small>{a.subtitle}</small></span><span className="analyst-check">{selected && <Check size={14} />}</span></button>; })}</div></section>
                <section className="finance-card"><div className="section-title"><Settings2 size={18} /><h2>分析选项</h2></div>
                  <div className="option-row"><div><strong>情绪分析</strong><small>基于有日期的社区样本，显示样本局限</small></div><input aria-label="启用情绪分析" type="checkbox" role="switch" checked={config.include_sentiment} onChange={e => updateConfig({ ...config, include_sentiment: e.target.checked })} /></div>
                  <div className="option-row"><div><strong>独立风险审查</strong><small>检查结论分歧、数据缺口与失效条件</small></div><input aria-label="启用风险审查" type="checkbox" role="switch" checked={config.include_risk} onChange={e => updateConfig({ ...config, include_risk: e.target.checked })} /></div>
                  <div className="form-grid comparison-fields"><label>比较基准<input value={config.benchmark} onChange={e => updateConfig({ ...config, benchmark: e.target.value.toUpperCase() })} /></label><label>可比公司（逗号分隔）<input value={config.peers.join(", ")} onChange={e => updateConfig({ ...config, peers: e.target.value.split(/[,，]/).slice(0, 4) })} placeholder="175.HK, 2015.HK" /></label></div>
                  <p className="field-note">比较对象由你指定；ETF和少数同业不会被表述为整个指数或行业。</p></section>
                </details>
              </fieldset>
              <div className="run-footer"><div><ShieldCheck size={18} /><span>只读研究 · 保留来源 · 不执行交易</span></div><button className="primary-button" type="submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={17} /> : <Play size={16} />}{busy ? "提交中…" : "开始研究"}</button></div>
            </form>
              {jobId ? <ResearchTask key={jobId} id={jobId} onReport={loadReport} />
                : <section className="finance-card task-progress"><h2>研究进度</h2><p className="muted">点击「开始研究」后，这里会显示排队状态、执行阶段和预计剩余时间。</p></section>}
            </div>}
            {tab === "schedules" && <SchedulePanel config={config} candidates={candidates} historyId={scheduleHistoryId} setHistoryId={setScheduleHistoryId}
              onTask={id => { setExecution({ id, from: "schedules" }); setTab("execution"); }} />}
            {tab === "tasks" && <TaskPanel onReport={loadReport} onTask={id => { setExecution({ id, from: "tasks" }); setTab("execution"); }} onSchedules={() => setTab("schedules")} />}
            {tab === "execution" && execution && <div className="workbench-page">
              <button className="chat-config-toggle" onClick={() => setTab(execution.from)}>返回{execution.from === "schedules" ? "定时任务" : "任务中心"}</button>
              <h1>执行详情</h1>
              <ResearchTask key={execution.id} id={execution.id} onReport={loadReport} />
            </div>}
            {(tab === "data" || tab === "ai") && <SettingsPanel section={tab} />}


            {tab === "report" && (!report ? <div className="empty-research"><div className="empty-orbit"><Layers3 size={32} /></div><span className="section-eyebrow">YOUR NEXT INSIGHT</span><h1>{running ? "研究已启动。" : "让证据连接成观点。"}</h1><p>{running ? "Agent 正在读取配置并准备研究。研究对话显示实时工具过程。" : "配置你的分析团队，生成一份可以追溯来源、继续追问和导出的研究报告。"}</p>{!running && <button className="primary-button" onClick={() => setTab("config")}>配置研究 <ChevronRight size={16} /></button>}</div> : <>
              <ReportView report={report} candidates={candidates} onSource={showSource} running={running && !savedReport} onStop={() => agent.abortRun()}
                onCheck={seed => { setCheckSeed(seed); setTab("review"); }} />
              {report.assessment && ["complete", "partial"].includes(report.status) && <div className="report-view">
                <button className="primary-button" aria-expanded={qaReportId === report.id} onClick={() => setQaReportId(qaReportId === report.id ? null : report.id)}>
                  <MessageSquare size={16} />{qaReportId === report.id ? "收起问答" : "就此研究提问"}
                </button>
                {qaReportId === report.id && <ReportQA key={report.id} id={report.id} symbol={report.symbol} />}
              </div>}
            </>)}

            {tab === "sources" && <div className="sources-view"><div className="section-eyebrow">EVIDENCE ROOM</div><h1>从观点，回到原始证据。</h1><p className="intro">{report ? `${report.symbol} · 截至 ${report.as_of} · ${report.evidence.sources.length} 条已接受证据` : "运行研究后，证据会在这里按来源和发布时间呈现。"}</p>
              {report?.evidence.methodology && <div className="methodology-note"><ShieldCheck size={18} /><p>{report.evidence.methodology}</p></div>}
              {report?.evidence.sources.map(s => <article id={`source-${s.id}`} key={s.id} className={`finance-card source-card ${sourceId === s.id ? "highlighted" : ""}`}><div className="source-meta"><span className="source-badge">{s.id}</span><span>{eventSourceNames[s.kind] ?? s.kind} · {s.provider}</span><time>{s.kind === "holder_change" && s.published_at ? `公告 ${s.published_at.slice(0, 10)}` : s.event_date ? `事件 ${s.event_date}` : s.published_at?.slice(0, 10)}</time></div><h3>{s.title}</h3><p>{s.excerpt_only ? "仅标题/摘要可用，不将其当作全文证据。" : "已获取正文或结构化数据。"}</p><details open={sourceId === s.id}><summary>查看证据内容</summary><pre>{s.content}</pre></details><a className="source-link" href={safeUrl(s.url)} target="_blank" rel="noreferrer">打开原始来源 <ExternalLink size={13} /></a>{s.filing_url && <a className="source-link" href={safeUrl(s.filing_url)} target="_blank" rel="noreferrer">打开公告佐证 <ExternalLink size={13} /></a>}</article>)}
              {!!report?.evidence.gaps.length && <section className="finance-card"><h3>数据覆盖与缺失</h3><ul>{report.evidence.gaps.map((g, i) => <li key={i}>{g}</li>)}</ul></section>}
            </div>}


        </div>}
      </main>
    </div>
  </div>;
}

function ReportView({ report, onSource, running, onStop, onCheck, candidates }: {
  report: Report; onSource: (id: string) => void; running: boolean; onStop: () => void; onCheck: (seed: CheckSeed) => void;
  candidates: ReturnType<typeof useReviewCandidates>;
}) {
  const events = report.evidence.sources.filter(source => source.event_date);
  const a = report.assessment;
  const metrics = report.evidence.metrics;
  const cited = (text: string) => <CitationText text={text} onSource={onSource} />;
  if (report.workflow) {
    const priceSources = report.evidence.sources.filter(source => source.kind === "prices" || source.kind === "calendar");
    return <div className="report-view">
      <div className="report-topline"><span className="section-eyebrow">定时简报</span><span className={`status-badge ${report.status}`}>{STATUS_NAMES[report.status]}</span></div>
      <div className="report-title"><div><h1>{report.symbol}</h1><p>截至 {report.as_of} · {report.evidence.sources.length} 条来源</p><p>生成于 <time dateTime={report.created_at}>{formatReportTime(report.created_at)}</time>（北京时间）</p></div>
        <div className="export-actions">{["md", "json", "pdf"].map(format => <a key={format} href={`/api/research/reports/${report.id}/export/${format}`}><Download size={13} />{format.toUpperCase()}</a>)}</div>
      </div>
      <section className="finance-card"><h2>摘要</h2><p>{a?.summary ?? "正在整理资料…"}</p>
        {!!a?.key_points.length && <ul className="finding-list">{a.key_points.map((point, i) => <li key={i}>{cited(point)}</li>)}</ul>}
        {report.evidence.methodology && <p className="muted">{report.evidence.methodology}</p>}
        {!!priceSources.length && <details className="brief-price-sources">
          <summary>交易日期与行情来源（{priceSources.length}）</summary>
          <div className="source-chips">{priceSources.map(source => <button type="button" key={source.id} onClick={() => onSource(source.id)}>
            {source.title} · {source.provider} <ArrowUpRight size={11} />
          </button>)}</div>
        </details>}
      </section>
      {!!report.evidence.gaps.length && <section className="finance-card"><h2>数据缺口</h2><ul>{report.evidence.gaps.map((gap, i) => <li key={i}>{gap}</li>)}</ul></section>}
    </div>;
  }
  const completed = report.stages.filter(s => s.status === "complete").length;
  const baseline = report.evidence.bars.reduce((latest, bar) =>
    (bar.volume ?? 0) > 0 && bar.date <= report.as_of && bar.date > latest ? bar.date : latest, "");
  const benchmark = mainlandCode.test(report.config.benchmark) ? report.config.benchmark : "510300.SH";
  const canCheck = mainlandCode.test(report.symbol) && !!baseline && ["complete", "partial"].includes(report.status);
  const candidateScope = canCheck && mainlandCode.test(report.config.benchmark)
    ? { symbol: report.symbol, session: baseline, benchmark: report.config.benchmark } : null;
  return <div className="report-view"><div className="report-topline"><span className="section-eyebrow">RESEARCH BRIEF</span><span className={`status-badge ${report.status}`}>{STATUS_NAMES[report.status] || report.status}</span></div>
    <div className="report-title"><div><h1>{report.symbol} <span>研究报告</span></h1><p>截至 {report.as_of} · {report.config.analysts.length} 位分析师 · {report.elapsed_seconds.toFixed(0)}s</p><p>生成于 <time dateTime={report.created_at}>{formatReportTime(report.created_at)}</time>（北京时间）</p></div><div className="export-actions">{["md", "json", "pdf"].map(f => <a key={f} aria-label={`导出 ${f.toUpperCase()}`} href={`/api/research/reports/${report.id}/export/${f}`}><Download size={13} />{f.toUpperCase()}</a>)}</div></div>
    {candidateScope && <div className="report-candidate-action">
      <CandidateButton key={report.id} scope={{ ...candidateScope, origin: "report", report_id: report.id }} candidates={candidates} />
    </div>}
    {running && report.status === "running" && <div className="run-progress"><div><LoaderCircle size={16} className="spin" /><span>{STAGE_NAMES[report.stages.find(s => s.status === "running")?.id || "data"]}正在工作</span><button onClick={onStop}><Square size={11} />停止</button></div><progress value={completed} max={report.stages.length} /></div>}
    <div className="stage-track">{report.stages.map(s => <details key={s.id} className={`stage-item ${s.status}`}><summary>{s.status === "complete" ? <Check size={12} /> : s.status === "running" ? <LoaderCircle size={12} className="spin" /> : <span className="stage-circle" />}{STAGE_NAMES[s.id]}</summary><p>{s.detail || STATUS_NAMES[s.status]}</p></details>)}</div>
    <div className="summary-grid"><section className="finance-card summary-main"><span className="mini-heading">研究观点</span><h2>{a?.stance || "交叉验证中"}</h2><p>{cited(a?.summary || "观点将在分析师完成研究后生成。点击上方阶段可查看实际进度，原生聊天保留工具输入和输出。")}</p></section><section className="finance-card score-card"><ShieldCheck size={23} /><span className="mini-heading">独立风险审查</span><strong>{a?.risk_level || "尚未完成"}</strong><small>{report.config.include_risk ? "结合已列明证据与数据缺口" : "本次未启用独立风险审查"}</small></section><section className="finance-card score-card"><div className="coverage-ring" style={{ "--coverage": `${report.evidence_coverage || 0}%` } as React.CSSProperties}><strong>{report.evidence_coverage ?? "—"}<small>%</small></strong></div><span className="mini-heading">证据覆盖率</span><small title={report.coverage_definition}>有来源发现的分析师比例<br />不代表模型预测准确率</small></section></div>
    {!!report.evidence.bars?.length && <section className="finance-card price-panel"><div className="section-title"><Activity size={17} /><h2>价格与技术指标</h2><span>{String(metrics.last_session || "")}</span></div><div className="metric-row">{[["收盘", metrics.close], ["MA20", metrics.ma20], ["MA60", metrics.ma60], ["RSI14", metrics.rsi14]].map(([name, value]) => <div key={String(name)}><small>{String(name)}</small><strong>{typeof value === "number" ? value.toFixed(2) : "—"}</strong></div>)}</div><div className="price-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={report.evidence.bars.slice(-120)}><defs><linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--finance-accent)" stopOpacity={0.3} /><stop offset="100%" stopColor="var(--finance-accent)" stopOpacity={0} /></linearGradient></defs><CartesianGrid vertical={false} stroke="var(--border)" /><XAxis dataKey="date" minTickGap={45} tick={{ fill: "var(--finance-muted)", fontSize: 10 }} tickFormatter={s => s.slice(5)} /><YAxis domain={["auto", "auto"]} width={48} tick={{ fill: "var(--finance-muted)", fontSize: 10 }} /><Tooltip contentStyle={{ background: "var(--finance-panel)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--foreground)" }} /><Area type="monotone" dataKey="close" name="收盘" stroke="var(--finance-accent)" strokeWidth={2} fill="url(#priceFill)" isAnimationActive={false} /></AreaChart></ResponsiveContainer></div><small className="field-note">代码计算 · 未复权日线 · 公司行动可能影响指标 · 非总回报</small></section>}
    {a && <section className="finance-card"><div className="section-title"><FileText size={17} /><h2>核心观点与验证条件</h2></div><ul className="finding-list">{a.key_points.map((v, i) => <li key={i}>{cited(v)}</li>)}</ul><h3>估值场景</h3>{a.valuation_scenarios.length ? a.valuation_scenarios.map((v, i) => <p key={i}>{cited(v)}</p>) : <p className="muted">证据或估值输入不足，本次未生成目标价。</p>}
      <h3>结论失效条件</h3>
      {canCheck && a.invalidation_conditions.length > 0 && <p className="field-note">可将报告条件作为背景，另设下一交易日可量化核对的指标。</p>}
      <ul className="review-checks">{a.invalidation_conditions.map((condition, index) => <li key={index} id={`report-condition-${index}`} tabIndex={-1}>
        <p>{cited(condition)}</p>
        {canCheck && condition.trim() && <button type="button" className="chat-config-toggle" onClick={() => onCheck({
          symbol: report.symbol, benchmark, baseline,
          report_origin: { report_id: report.id, condition_index: index, condition },
        })}>记录次日验证 <ArrowUpRight size={12} /></button>}
      </li>)}</ul>
    </section>}
    {Object.entries(report.findings).map(([role, f]) => <section className="finance-card analyst-finding" key={role}><div className="section-title"><span className="analyst-icon small">{ANALYSTS.find(a => a.id === role)?.icon || "◈"}</span><h2>{STAGE_NAMES[role]}</h2><span className={`stance ${f.stance === "偏多" ? "positive" : f.stance === "偏空" ? "negative" : ""}`}>{f.stance}</span></div><p>{cited(f.summary)}</p><ul className="finding-list">{f.findings.map((v, i) => <li key={i}>{cited(v)}</li>)}</ul>{!!f.risks.length && <details><summary>风险与反方观点</summary><ul>{f.risks.map((v, i) => <li key={i}>{cited(v)}</li>)}</ul></details>}{!!f.missing.length && <div className="missing-note">{f.missing.join("；")}</div>}<div className="source-chips">{f.source_ids.map(id => <button key={id} onClick={() => onSource(id)}>{id} <ArrowUpRight size={11} /></button>)}</div></section>)}
    {!!events.length && <section className="finance-card"><div className="section-title"><Activity size={17} /><h2>A 股专属事件</h2></div>
      <ul className="review-checks">{events.map(event => <li key={event.id}><strong>{event.title}</strong><p>{event.content}</p>
        <button type="button" className="chat-config-toggle" onClick={() => onSource(event.id)}>查看证据 [{event.id}]</button></li>)}</ul>
    </section>}
    {!!report.evidence.gaps.length && <section className="finance-card gaps-card"><div className="section-title"><ShieldCheck size={17} /><h2>数据覆盖与研究限制</h2></div><ul>{report.evidence.gaps.map((v, i) => <li key={i}>{v}</li>)}</ul></section>}
    <footer className="report-footnote">本报告用于研究与学习，不构成个性化投资建议。<br />{report.evidence.sources.length} 条来源 · {report.id.slice(0, 8)}</footer>
  </div>;
}
