import {
  defaultApplyEvents,
  EventType,
  HttpAgent,
  type BaseEvent,
  type RunAgentInput,
  type RunStartedEvent,
  type MessagesSnapshotEvent,
} from "@copilotkit/react-core/v2";
import { from, lastValueFrom, reduce } from "rxjs";
import type { Report } from "@/lib/research";
import {orderMessageSnapshot} from "@/lib/message-snapshot";

export async function readResearchHistory(threadId: string, signal: AbortSignal, allowMissing = false) {
  const started = performance.now();
  const timeout = AbortSignal.timeout(20_000);
  try {
    return await restoreHistory(threadId, AbortSignal.any([signal, timeout]), allowMissing, started);
  } catch (error) {
    if (timeout.aborted && !signal.aborted) throw new Error("读取会话历史超时，请重试。");
    throw error;
  }
}

const historyCache = new Map<string, Awaited<ReturnType<typeof readResearchHistory>>>();
export function cachedResearchHistory(threadId: string) {
  const value = historyCache.get(threadId);
  return value ? structuredClone(value) : undefined;
}

async function restoreHistory(threadId: string, signal: AbortSignal, allowMissing: boolean, started: number) {
  const response = await fetch(
    `/api/copilotkit/threads/${encodeURIComponent(threadId)}/events?agentId=default`,
    { signal, cache: "no-store" },
  );
  if (allowMissing && response.status === 404) return { messages: [], state: {}, incomplete: false };
  if (!response.ok) throw new Error("无法读取会话历史，请重试。");
  const received = performance.now();
  const { events }: { events: BaseEvent[] } = await response.json();
  const parsed = performance.now();
  const input: RunAgentInput = {
    threadId, runId: "history", messages: [], state: {}, tools: [], context: [], forwardedProps: {},
  };

  // Reconstruct messages locally. No live agent or tool subscribers run during replay.
  const replay = new HttpAgent({ url: response.url, threadId });
  const history = await lastValueFrom(
    defaultApplyEvents(input, from(events.filter(event => event.type !== EventType.RAW)), replay, [{
      onEvent: ({ event, messages }) => {
        if(event.type===EventType.MESSAGES_SNAPSHOT)return {messages:orderMessageSnapshot(messages,(event as MessagesSnapshotEvent).messages)};
        if (event.type !== EventType.RUN_STARTED) return;
        const submitted = (event as RunStartedEvent).input?.messages ?? [];
        const knownIds = new Set(messages.map(message => message.id));
        const added = submitted.filter(message => !knownIds.has(message.id));
        if (added.length) return { messages: [...messages, ...added] };
      },
    }]).pipe(reduce((history, mutation) => ({
      messages: mutation.messages ?? history.messages,
      state: mutation.state ?? history.state,
    }), { messages: input.messages, state: input.state })),
  );
  const replayed = performance.now();
  const report = history.state.research as Report | undefined;
  // A report may finish locally after the chat connection stopped saving events.
  if (report?.status === "running" && report.id) {
    const saved = await fetch(`/api/research/reports/${encodeURIComponent(report.id)}`, { signal, cache: "no-store" })
      .then(result => result.ok ? result.json() as Promise<Report> : null)
      .catch(() => null);
    if (saved) history.state = { ...history.state, research: saved };
  }
  const answered = new Set(history.messages.flatMap(message =>
    message.role === "tool" ? [message.toolCallId] : [],
  ));
  const incomplete = history.messages.some(message =>
    message.role === "assistant" && message.toolCalls?.some(call => !answered.has(call.id)),
  );
  signal.throwIfAborted();
  const result = { ...history, incomplete };
  historyCache.delete(threadId);
  historyCache.set(threadId, structuredClone(result));
  if (historyCache.size > 12) historyCache.delete(historyCache.keys().next().value!);
  performance.measure("research-history:request", { start: started, end: received });
  performance.measure("research-history:parse", { start: received, end: parsed });
  performance.measure("research-history:replay", { start: parsed, end: replayed });
  return result;
}
