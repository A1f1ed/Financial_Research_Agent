import { HttpAgent } from '@ag-ui/client';
import { CopilotKitIntelligence, CopilotRuntime, createCopilotRuntimeHandler } from '@copilotkit/runtime/v2';
import { AGENT_ID } from './folio-contract';
import { userFromRequest } from './folio-session';

let intelligenceClient: CopilotKitIntelligence | undefined;
export function getIntelligence() {
  if (intelligenceClient) return intelligenceClient;
  const apiKey = process.env.CPK_INTELLIGENCE_API_KEY;
  if (!apiKey) throw new Error('CopilotKit cloud credentials are not configured.');
  intelligenceClient = new CopilotKitIntelligence({
    apiKey,
    getLearningContainerId: ({ input }) => input.state?.learningEnabled === true ? 'folio-research' : null,
  });
  return intelligenceClient;
}
let handler: ReturnType<typeof createCopilotRuntimeHandler> | undefined;
export function getCopilotHandler() {
  if (handler) return handler;
  const apiKey = process.env.CPK_INTELLIGENCE_API_KEY;
  const internalSecret = process.env.FOLIO_INTERNAL_SECRET;
  if (!apiKey || !internalSecret) throw new Error('CopilotKit cloud and agent credentials are not configured.');
  const intelligence = getIntelligence();
  const runtime = new CopilotRuntime({
    agents: {
      [AGENT_ID]: new HttpAgent({
        url: `${(process.env.PYTHON_AGENT_URL ?? 'http://localhost:8000').replace(/\/$/, '')}/agent`,
        headers: { Authorization: `Bearer ${internalSecret}` },
        description: 'Python LangChain / LangGraph 金融研究助手。支持共享状态、研究计划确认和前端工具。',
      }),
    },
    intelligence,
    identifyUser: userFromRequest,
    forwardHeaders: { useDefaultDenylist: true, deny: ['authorization', 'cookie'] },
  });
  handler = createCopilotRuntimeHandler({ runtime, basePath: '/api/copilotkit' });
  return handler;
}
