'use client';

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { CopilotKit, useAgent, useFrontendTool, useHumanInTheLoop } from '@copilotkit/react-core/v2';
import { useCopilotKit } from '@copilotkit/react-core/v2/context';
import useSWR, { useSWRConfig } from 'swr';
import { AGENT_ID, approvalSchema, initialResearchState, modeSchema, researchModes, summarySchema, type ResearchState } from '../lib/folio-contract';
import { ApprovalCard, SummaryCard } from './research-agent-cards';

const fetchJSON = async (url: string) => {
  const response = await fetch(url);
  if (!response.ok) throw new Error('服务暂不可用');
  return response.json();
};
function useController() {
  const { agent, isReady } = useAgent({ agentId: AGENT_ID, throttleMs: 50 });
  const { copilotkit } = useCopilotKit();
  const { mutate } = useSWRConfig();
  const { data: health, mutate: refreshHealth } = useSWR<{ configured: boolean; python: boolean; cloudConfigured: boolean; financialData: boolean }>('/api/agent/status', fetchJSON, { refreshInterval: 30000, shouldRetryOnError: false });
  const [error, setError] = useState<string | null>(null);
  const state = { ...initialResearchState, ...agent.state } as ResearchState;
  const setState = (patch: Partial<ResearchState>) => agent.setState({ ...initialResearchState, ...agent.state, ...patch });
  useEffect(() => {
    if (!isReady) return;
    const { unsubscribe } = agent.subscribe({
      onRunErrorEvent: ({ event }) => setError(event.message.startsWith('AI Gateway 需要') ? event.message : '研究未能完成，请检查 Python Agent 和模型服务后重试。'),
      onRunFailed: () => setError(previous => previous ?? '连接中断。已收到的内容会保留，请稍后重试。'),
      onRunFinalized: () => { void mutate('/api/agent/threads'); },
    });
    return unsubscribe;
  }, [agent, isReady, mutate]);
  useHumanInTheLoop({
    agentId: AGENT_ID,
    name: 'approve_research_plan',
    description: '研究开始前让用户确认研究范围和数据限制。只有明确同意才能继续。',
    parameters: approvalSchema,
    render: ({ args, status, respond, result }) => <ApprovalCard topic={args.topic ?? ''} steps={args.steps ?? []} status={status} result={result} onRespond={respond ? async approved => { setState({ stage: approved ? 'researching' : 'cancelled' }); await respond({ approved }); } : undefined}/>,
  });
  useFrontendTool({
    agentId: AGENT_ID, name: 'show_research_summary',
    description: '在 Folio 对话中呈现研究摘要卡片。必须标注证据来源与日期，不得伪造实时金融数据。',
    parameters: summarySchema,
    handler: async () => ({ displayed: true }),
    render: ({ args, status }) => <SummaryCard summary={args} pending={status === 'inProgress'}/>,
  });
  useFrontendTool({
    agentId: AGENT_ID, name: 'set_research_mode',
    description: '仅在用户明确要求时切换 Folio 的研究模式，同时同步前端与 Python Agent 状态。',
    parameters: modeSchema,
    handler: async ({ mode }) => { setState({ mode }); return { mode, updated: true }; },
    render: ({ args }) => <div className="agent-tool-note">研究模式已同步：{args.mode ?? '处理中'}</div>,
  });
  const submit = async (question: string) => {
    if (!question.trim() || agent.isRunning) return false;
    if (!isReady || !health?.python) { setError('Python Agent 尚未就绪，请检查连接后重试。'); void refreshHealth(); return false; }
    setError(null);
    setState({ stage: 'planning' });
    agent.addMessage({ id: crypto.randomUUID(), role: 'user', content: question.trim().slice(0, 2000) });
    try { await copilotkit.runAgent({ agent }); return true; }
    catch { setError(previous => previous ?? '研究请求未完成。请检查服务连接，或修改问题后重试。'); return false; }
  };
  const stop = async () => {
    try { await copilotkit.stopAgent({ agent }); setState({ stage: 'cancelled' }); }
    catch { setError('停止请求未确认，请稍后检查会话状态。'); }
  };
  const newThread = async () => {
    if (agent.isRunning) await stop();
    agent.threadId = crypto.randomUUID();
    agent.setMessages([]);
    agent.setState({ ...initialResearchState, mode: state.mode });
    setError(null);
  };
  const loadThread = async (threadId: string) => {
    if (agent.isRunning) return;
    agent.threadId = threadId;
    agent.setMessages([]);
    agent.setState(initialResearchState);
    setError(null);
    try { await copilotkit.connectAgent({ agent }); }
    catch { setError('无法恢复此研究会话，请稍后重试。'); }
  };
  return { agent, isReady, state, setState, mode: researchModes.includes(state.mode) ? state.mode : '深度研究', setMode: (mode: string) => { if (researchModes.includes(mode as ResearchState['mode'])) setState({ mode: mode as ResearchState['mode'] }); }, submit, stop, newThread, loadThread, error, clearError: () => setError(null), health, refreshHealth };
}
type Controller = ReturnType<typeof useController>;
const AgentContext = createContext<Controller | null>(null);
function ControllerProvider({ children }: { children: ReactNode }) {
  const controller = useController();
  return <AgentContext.Provider value={controller}>{children}</AgentContext.Provider>;
}
export function FolioAgentProvider({ children }: { children: ReactNode }) {
  return <CopilotKit runtimeUrl="/api/copilotkit" agent={AGENT_ID} showDevConsole={false} showIntelligenceIndicator={false} enableInspector={false}><ControllerProvider>{children}</ControllerProvider></CopilotKit>;
}
export function useFolioAgent() {
  const context = useContext(AgentContext);
  if (!context) throw new Error('FolioAgentProvider is required.');
  return context;
}
