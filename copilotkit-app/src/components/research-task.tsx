"use client";

import { useT } from "@/hooks/use-language";

import { useContext, useEffect, useRef, useState } from "react";
import { Activity, ArrowUpRight, Check, Clock3, LoaderCircle, MessageSquare } from "lucide-react";
import { CopilotChat, CopilotChatView, type CopilotChatViewProps, CopilotChatConfigurationProvider, useAgent } from "@copilotkit/react-core/v2";
import { FollowupContext, useFollowupView } from "@/components/chat-followups";
import { cachedResearchHistory, readResearchHistory } from "@/lib/research-history";
import { STAGE_NAMES, STATUS_NAMES, type Report, type ResearchConfig } from "@/lib/research";
import { researchRequest } from "@/components/workbench-panels";

type Progress = {
  name: string;
  config: ResearchConfig;
  workflow?: string | null;
  status: string;
  error?: string;
  report_id?: string;
  has_assessment: boolean;
  stages: Report["stages"];
  elapsed_seconds: number;
};

const terminal = new Set(["complete", "partial", "failed", "cancelled"]);
const stageBudget = (stage: string) => stage === "data" ? 35 : stage === "synthesis" ? 25 : 16;

function estimateRemaining(task: Progress) {
  const settled = task.stages.filter(stage => stage.status === "complete" || stage.status === "failed");
  const expectedSettled = settled.reduce((sum, stage) => sum + stageBudget(stage.id), 0);
  const factor = expectedSettled ? Math.max(0.4, Math.min(3, (task.elapsed_seconds + 30) / (expectedSettled + 30))) : 1;
  const remaining = task.stages.filter(stage => stage.status === "pending" || stage.status === "running")
    .reduce((sum, stage) => sum + stageBudget(stage.id), 0) * factor;
  if (!remaining) return "即将结束";
  return remaining < 60 ? `约 ${Math.max(10, Math.ceil(remaining / 10) * 10)} 秒` : `约 ${Math.ceil(remaining / 60)} 分钟`;
}

export function ResearchTask({ id, onReport }: { id: string; onReport: (id: string) => void }) {
  const t = useT();
  const [task, setTask] = useState<Progress | null>(null);
  const [error, setError] = useState("");
  const [qaOpen, setQaOpen] = useState(false);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    panel.current?.scrollIntoView({ block: "start" });
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const result = await researchRequest<Progress>(`tasks/${id}`);
        if (!active) return;
        setTask(result);
        setError("");
        if (terminal.has(result.status)) return;
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "暂时无法读取进度。");
      }
      if (active) timer = setTimeout(refresh, 2500);
    }
    void refresh();
    return () => { active = false; clearTimeout(timer); };
  }, [id]);

  const finished = task ? terminal.has(task.status) : false;
  const completed = task?.stages.filter(stage => stage.status === "complete" || stage.status === "failed").length ?? 0;
  return <section ref={panel} className="finance-card task-progress" aria-label={t("当前研究进度")}>
    <div className="workbench-item-head">
      <div><span className="section-eyebrow">{t("当前研究")}</span><h2>{t(task?.name ?? "正在读取任务…")}</h2></div>
      {task && <span className={`status-badge ${task.status}`}>{t(task.status === "queued" ? "排队中" : STATUS_NAMES[task.status] ?? task.status)}</span>}
    </div>
    {error && <p role="alert">{t(error)}</p>}
    {task && <>
      <p className="muted">{t(task.workflow ? task.config.market : task.config.symbol)}{t("· 截至")}{t(task.config.as_of)}</p>
      {task.status === "queued" && <p role="status"><Clock3 size={15} />{t("正在排队，进入运行后显示预计时间。")}</p>}
      {task.status === "running" && <p role="status"><LoaderCircle className="spin" size={15} /> {t(task.stages.length
        ? `预计剩余 ${estimateRemaining(task)} · 已处理 ${completed}/${task.stages.length} 个阶段`
        : "正在准备研究流程…")}</p>}
      {task.status === "running" && task.stages.length > 0 && <progress max={task.stages.length} value={completed} aria-label={t("研究进度")} />}
      {task.stages.length > 0 && <ol className="task-stage-list">
        {task.stages.map(stage => <li key={stage.id} data-status={stage.status}>
          <details>
            <summary>{t(stage.status === "complete" ? <Check size={15} /> : stage.status === "running" ? <LoaderCircle className="spin" size={15} /> : <Activity size={15} />)}
              <span>{t(STAGE_NAMES[stage.id] ?? stage.id)}</span><small>{t(STATUS_NAMES[stage.status] ?? stage.status)}</small>
            </summary>
            <p>{t(stage.detail || STATUS_NAMES[stage.status])}</p>
          </details>
        </li>)}
      </ol>}
      {task.error && <p role="alert">{t(task.error)}</p>}
      {task.report_id && <div className="workbench-actions">
        <button className="chat-config-toggle" onClick={() => onReport(task.report_id!)}>{t("查看报告与证据")}<ArrowUpRight size={15} /></button>
        {finished && task.has_assessment && <button className="primary-button" aria-expanded={qaOpen} onClick={() => setQaOpen(open => !open)}>
          <MessageSquare size={16} />{t(qaOpen ? "收起问答" : "就此研究提问")}
        </button>}
      </div>}
      {qaOpen && task.report_id && <ReportQA key={task.report_id} id={task.report_id} symbol={task.workflow ? task.name : task.config.symbol} />}
    </>}
  </section>;
}

export function ReportQA({ id, symbol }: { id: string; symbol: string }) {
  const agentId = `research-qa-${id}`;
  return <CopilotChatConfigurationProvider agentId={agentId} threadId={id}>
    <ReportChat id={id} agentId={agentId} symbol={symbol} />
  </CopilotChatConfigurationProvider>;
}

function ReportChatView(props: CopilotChatViewProps) {
  const followups = useFollowupView(props);
  const scope = useContext(FollowupContext);
  return <CopilotChatView {...props} {...followups} onSubmitMessage={props.onSubmitMessage && (value => {
    if (scope?.reportId) scope.agent.setState({ ...scope.agent.state, research_qa_report_id: scope.reportId });
    props.onSubmitMessage?.(value);
  })} />;
}

function ReportChat({ id, agentId, symbol }: { id: string; agentId: string; symbol: string }) {
  const t = useT();
  const { agent, isReady } = useAgent({ agentId, threadId: id, runtimeAgentId: "default" });
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [attachmentError, setAttachmentError] = useState("");
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    panel.current?.scrollIntoView({ block: "start" });
  }, []);
  useEffect(() => {
    if (!isReady) return;
    const controller = new AbortController();
    const cached = cachedResearchHistory(id);
    if (cached) {
      agent.setMessages(cached.messages);
      agent.setState({ ...cached.state, research_qa_report_id: id });
      setReady(true);
    }
    const initialMessages = agent.messages;
    const subscription = agent.subscribe({ onRunInitialized: () => controller.abort() });
    readResearchHistory(id, controller.signal, true).then(history => {
      if (controller.signal.aborted || agent.isRunning || agent.messages !== initialMessages) return;
      agent.setMessages(history.messages);
      agent.setState({ ...history.state, research_qa_report_id: id });
      setReady(true);
    }).catch(err => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "无法读取报告问答。");
    });
    return () => { controller.abort(); subscription.unsubscribe(); };
  }, [agent, id, isReady, retry]);
  return <div ref={panel} className="report-qa">
    <h3>{t(symbol)}{t("· 报告问答")}</h3>
    {error && <p role="alert">{t(error)} <button className="chat-config-toggle" onClick={() => { setError(""); setRetry(value => value + 1); }}>{t("重试")}</button></p>}
    {!ready && !error && <p role="status">{t("正在载入报告问答…")}</p>}
    {ready && <div className="report-qa-chat">
      <FollowupContext.Provider value={{ agent, threadId: id, reportId: id }}>
      <CopilotChat agentId={agentId} threadId={id} chatView={ReportChatView}
        attachments={{
          enabled: true, accept: ".txt,.md,.csv,text/plain,text/markdown,text/csv", maxSize: 65536,
          onUploadFailed: () => setAttachmentError("请选择 64 KB 以内的 UTF-8 TXT、Markdown 或 CSV 文件。"),
          onUpload: async file => {
            const data = new Uint8Array(await file.arrayBuffer());
            new TextDecoder("utf-8", { fatal: true }).decode(data);
            const extension = file.name.split(".").pop()?.toLowerCase();
            const mimeType = extension === "csv" ? "text/csv" : extension === "md" ? "text/markdown" : "text/plain";
            setAttachmentError("");
            return { type: "data", value: btoa(Array.from(data, byte => String.fromCharCode(byte)).join("")), mimeType };
          },
        }}
        labels={{ welcomeMessageText: t("这份研究还有哪些值得追问？"), chatInputPlaceholder: t("例如：报告里哪些证据支持这个结论？"), chatInputToolbarAddButtonLabel: t("添加附件"), chatDisclaimerText: t("支持 TXT、Markdown、CSV（64 KB 内），请结合原始来源核对结论。") }} />
      </FollowupContext.Provider>
    </div>}
    {attachmentError && <p role="alert">{t(attachmentError)}</p>}
  </div>;
}
