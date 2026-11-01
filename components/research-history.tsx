'use client';
import useSWR from 'swr';
import { ChevronRight, MessageSquare } from 'lucide-react';
import { useFolioAgent } from './folio-agent-provider';

type Thread = { id: string; name: string | null; lastRunAt?: string; createdAt?: string };
async function getThreads(url: string): Promise<{ threads: Thread[] }> {
  const response = await fetch(url);
  if (!response.ok) throw new Error('无法读取研究历史');
  return response.json();
}
export function ResearchHistory({ onOpen }: { onOpen: () => void }) {
  const { loadThread, agent } = useFolioAgent();
  const { data, error, isLoading, mutate } = useSWR('/api/agent/threads', getThreads, { shouldRetryOnError: false });
  return <section className="recent-section agent-history"><div className="section-heading"><h2>我的研究会话</h2><span>CopilotKit 云端保存</span></div>{isLoading && <p className="agent-history-note">正在载入研究历史…</p>}{error && <p className="agent-error" role="alert">暂时无法读取云端会话。<button onClick={() => void mutate()}>重试</button></p>}{data?.threads.length === 0 && <p className="agent-history-note">还没有研究会话。发起你的第一个问题后，会在这里保存。</p>}<div className="report-list">{data?.threads.map(thread => <button className="agent-thread" key={thread.id} disabled={agent.isRunning} onClick={() => { onOpen(); void loadThread(thread.id); }}><span className="report-icon green"><MessageSquare size={18}/></span><span><strong>{thread.name ?? '未命名研究'}</strong><small>{thread.lastRunAt || thread.createdAt ? new Date(thread.lastRunAt ?? thread.createdAt!).toLocaleString('zh-CN') : '已保存的研究会话'}</small></span><ChevronRight size={16}/></button>)}</div></section>;
}
