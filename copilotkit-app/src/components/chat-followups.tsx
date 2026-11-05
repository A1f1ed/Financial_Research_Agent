"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { type AbstractAgent, type Message, type CopilotChatViewProps } from "@copilotkit/react-core/v2";

export const FollowupContext = createContext<{ agent: AbstractAgent; threadId?: string; reportId?: string } | null>(null);

function latestTurn(messages: readonly Message[]) {
  const userIndex = messages.findLastIndex(message => message.role === "user");
  if (userIndex < 0) return null;
  const user = messages[userIndex];
  const answer = messages.slice(userIndex + 1).findLast(message => message.role === "assistant");
  if (user.role !== "user" || answer?.role !== "assistant" || answer.toolCalls?.length || !answer.content?.trim()) return null;
  const question = typeof user.content === "string" ? user.content : user.content
    ?.flatMap(part => part.type === "text" ? [part.text] : []).join("\n");
  if (!question?.trim()) return null;
  return { message_id: answer.id, question: question.trim().slice(0, 1200), answer: answer.content.trim().slice(0, 3200) };
}

export function useFollowupView(props: CopilotChatViewProps) {
  const { agent, threadId, reportId } = useContext(FollowupContext) ?? {};
  const messageId = latestTurn(props.messages ?? [])?.message_id;
  const key = threadId && messageId ? JSON.stringify([threadId, messageId, reportId ?? ""]) : null;
  const [loaded, setLoaded] = useState<{ key: string; questions: string[] } | null>(null);
  const [generated, setGenerated] = useState<{ key: string; questions: string[] } | null>(null);

  useEffect(() => {
    if (!agent || !threadId) return;
    const controller = new AbortController();
    const liveRuns = new Set<string>();
    const subscription = agent.subscribe({
      onRunInitialized: ({ input }) => { if (input.threadId === threadId) liveRuns.add(input.runId); },
      onRunFinalized: ({ input }) => { liveRuns.delete(input.runId); },
      onRunFinishedEvent: (run) => {
        const { input, messages, outcome } = run;
        if (!liveRuns.delete(input.runId) || outcome !== "success" || run.pendingToolCallIds.length) return;
        const turn = latestTurn(messages);
        if (!turn || input.messages.some(message => message.id === turn.message_id)) return;
        const resultKey = JSON.stringify([threadId, turn.message_id, reportId ?? ""]);
        void fetch("/api/research/followups", {
          method: "POST", signal: controller.signal, headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...turn, thread_id: threadId, report_id: reportId }),
        }).then(response => response.ok ? response.json() as Promise<{ questions: string[] }> : null)
          .then(result => {
            if (!controller.signal.aborted && result && latestTurn(agent.messages)?.message_id === turn.message_id) {
              setGenerated({ key: resultKey, questions: result.questions });
            }
          }).catch(() => {});
      },
    });
    return () => { subscription.unsubscribe(); controller.abort(); };
  }, [agent, threadId, reportId]);

  useEffect(() => {
    if (!key || !threadId || !messageId || props.isRunning) return;
    const controller = new AbortController();
    const query = new URLSearchParams({ thread_id: threadId, message_id: messageId, report_id: reportId ?? "" });
    void fetch(`/api/research/followups?${query}`, { cache: "no-store", signal: controller.signal })
      .then(response => response.ok ? response.json() as Promise<{ questions: string[] }> : null)
      .then(result => { if (result && !controller.signal.aborted) setLoaded({ key, questions: result.questions }); })
      .catch(() => {});
    return () => controller.abort();
  }, [key, threadId, messageId, reportId, props.isRunning]);

  const questions = generated?.key === key ? generated?.questions : loaded?.key === key ? loaded?.questions : undefined;
  return {
    suggestions: props.isRunning || props.isConnecting ? [] : (questions ?? []).map(message => ({ title: message, message, isLoading: false })),
    onSelectSuggestion: (suggestion: { message: string }) => props.onInputChange?.(suggestion.message),
  };
}
