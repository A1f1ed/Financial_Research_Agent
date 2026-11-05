"use client";
import { CopilotChatConfigurationProvider } from "@copilotkit/react-core/v2";
import { ResearchWorkspace } from "@/components/research-workspace";

export default function HomePage() {
  return <CopilotChatConfigurationProvider agentId="default"><ResearchWorkspace /></CopilotChatConfigurationProvider>;
}
