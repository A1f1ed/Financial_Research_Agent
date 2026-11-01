'use client';

import { useEffect, useRef } from 'react';
import { useRenderToolCall } from '@copilotkit/react-core/v2';
import { Activity, ArrowDownToLine, LoaderCircle, ShieldCheck, Square, X } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { useFolioAgent } from './folio-agent-provider';

export function ResearchConversation() {
  const { agent, state, setState, isReady, health, error, clearError, stop, refreshHealth } = useFolioAgent();
  const renderToolCall = useRenderToolCall();
  const bottom = useRef<HTMLDivElement>(null);
  const hasMessages = agent.messages.some(message => message.role === 'user');
  const busy = agent.isRunning;
  useEffect(() => { if (hasMessages) bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [hasMessages, agent.messages.length]);
  const download = () => {
    const lines = agent.messages.flatMap(message => {
      if (message.role === 'tool' || message.role === 'system' || message.role === 'developer') return [];
      return typeof message.content === 'string' && message.content ? [`${message.role === 'user' ? '研究问题' : 'Folio'}\n${message.content}\n`] : [];
    });
    const blob = new Blob([`Folio 研究会话\n\n${lines.join('\n')}\nAI 辅助研究，不构成投资建议。外部数据以正文所列来源与观察日期为准，不保证实时性。`], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = 'Folio-研究会话.txt'; link.click(); URL.revokeObjectURL(url);
  };
  return <section className="agent-workspace" aria-label="Folio 研究对话"><div className="agent-connection"><span className={isReady && health?.python ? 'agent-status connected' : 'agent-status'}><i/>{isReady && health?.python ? 'Python Agent 已连接' : '正在检查 Agent 连接'}</span><span>LangGraph · AG-UI · {health?.financialData ? 'Vibe-Trading MCP 已连接' : '金融数据未连接'}</span>{health && (!health.python || !health.modelConfigured) && <button onClick={() => void refreshHealth()}>重新检查</button>}</div>
    <details className="agent-preferences"><summary>研究偏好与共享状态<ShieldCheck size={13}/></summary><div className="agent-preferences-grid"><label>投资视角<select aria-label="投资视角" value={state.horizon} disabled={busy} onChange={event => setState({ horizon: event.target.value })}><option>长期（1 年以上）</option><option>中期（3–12 个月）</option><option>短期（3 个月以内）</option></select></label><label>风险偏好<select aria-label="风险偏好" value={state.riskTolerance} disabled={busy} onChange={event => setState({ riskTolerance: event.target.value })}><option>稳健</option><option>均衡</option><option>积极</option></select></label></div><label className="agent-learning-consent"><input type="checkbox" checked={state.learningEnabled} disabled={hasMessages || busy} onChange={event => setState({ learningEnabled: event.target.checked })}/>将此会话贡献到项目学习空间（开始前选择）</label><p>开启后会将本会话发送至 CopilotKit 云学习空间，提炼可复用研究方法；技能候选需人工审核，不会自动发布。请勿贡献敏感内容。匿名工作空间使用安全 Cookie 隔离；删除 Cookie 后将无法找回会话。</p></details>
    {error && <div className="agent-error" role="alert"><span>{error}</span><button aria-label="关闭错误提示" onClick={clearError}><X size={15}/></button></div>}
    {hasMessages && <><div className="section-heading agent-conversation-heading"><h2><Activity size={16}/>当前研究</h2><div>{busy && <button onClick={() => void stop()}><Square size={12}/>停止</button>}<button onClick={download} disabled={busy}><ArrowDownToLine size={13}/>导出会话</button></div></div><div className="agent-messages" aria-live="polite" aria-relevant="additions text">{agent.messages.map(message => {
      if (message.role !== 'user' && message.role !== 'assistant') return null;
      return <div key={message.id} className={`agent-message ${message.role}`}><span className="agent-message-label">{message.role === 'user' ? '你的研究问题' : 'FOLIO'}</span>{typeof message.content === 'string' && message.content && <div className="agent-markdown"><ReactMarkdown components={{ a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> }}>{message.content}</ReactMarkdown></div>}{message.role === 'assistant' && message.toolCalls?.map(call => <div className="agent-tool-render" key={call.id}>{renderToolCall({ toolCall: call, toolMessage: agent.messages.find(m => m.role === 'tool' && m.toolCallId === call.id) as Parameters<typeof renderToolCall>[0]['toolMessage'] })}</div>)}</div>;
    })}{busy && <p className="agent-working" role="status"><LoaderCircle size={14} className="agent-spinner"/>{state.stage === 'awaiting_approval' ? '等待你确认研究计划' : 'Agent 正在处理研究…'}</p>}<div ref={bottom}/></div></>}
  </section>;
}
