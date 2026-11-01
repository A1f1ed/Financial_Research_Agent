'use client';

import { useState } from 'react';
import { Check, ShieldCheck, Sparkles } from 'lucide-react';
import type { ResearchSummary } from '../lib/folio-contract';

export function ApprovalCard({ topic, steps, status, result, onRespond }: { topic: string; steps: (string | undefined)[]; status: string; result?: string; onRespond?: (approved: boolean) => Promise<void> }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);
  const respond = async (approved: boolean) => {
    if (!onRespond || pending) return;
    setPending(true); setError(false);
    try { await onRespond(approved); }
    catch { setError(true); setPending(false); }
  };
  const complete = status === 'complete';
  let approved = false;
  try { approved = Boolean(result && JSON.parse(result)?.approved); } catch { approved = false; }
  return <section className="agent-card approval-card" aria-label="研究计划确认"><div className="agent-card-heading"><ShieldCheck size={18}/><strong>先对齐问题，再开始研究</strong><span>人工确认</span></div><h3>{topic || '正在准备研究范围…'}</h3><ol>{steps.map((step, i) => <li key={i}>{step}</li>)}</ol><p className="agent-evidence">将尝试通过只读 MCP 查询公开金融数据，保留来源和日期；数据可能延迟或不可用。不会执行任何交易，请勿提供保密信息。</p>{complete ? <p className="agent-decision"><Check size={14}/>{approved ? '已同意研究计划' : '已取消研究计划'}</p> : <div className="agent-card-actions"><button className="secondary-button" disabled={!onRespond || pending} onClick={() => void respond(false)}>取消</button><button className="primary-button" disabled={!onRespond || pending} onClick={() => void respond(true)}>{pending ? '正在提交…' : '确认并开始研究'}</button></div>}{error && <p role="alert">确认未提交成功，请重试。</p>}</section>;
}
export function SummaryCard({ summary, pending }: { summary: Partial<ResearchSummary>; pending: boolean }) {
  return <article className="agent-card summary-card"><div className="agent-card-heading"><Sparkles size={17}/><strong>Folio 研究摘要</strong><span>{pending ? '生成中' : summary.evidence ?? '未核验'}</span></div><h3>{summary.title || '正在整理洞察…'}</h3><p>{summary.thesis}</p>{!!summary.risks?.length && <><h4>关键风险</h4><ul>{summary.risks.map((risk, i) => <li key={i}>{risk}</li>)}</ul></>}{!!summary.nextSteps?.length && <><h4>下一步验证</h4><ul>{summary.nextSteps.map((step, i) => <li key={i}>{step}</li>)}</ul></>}<p className="agent-evidence">AI 辅助分析 · 数字与事实须独立核验 · 不构成投资建议</p></article>;
}
