import { z } from 'zod';

export const AGENT_ID = 'folio_research';
export const researchModes = ['深度研究', '快速概览', '对比分析'] as const;
export const approvalSchema = z.object({ topic: z.string().max(2000), steps: z.array(z.string().max(200)).max(6) });
export const summarySchema = z.object({
  title: z.string().max(200), thesis: z.string().max(1500),
  risks: z.array(z.string().max(300)).max(6), nextSteps: z.array(z.string().max(300)).max(6),
  evidence: z.enum(['未核验', '用户提供的数据', '外部数据（见来源与日期）']),
});
export const modeSchema = z.object({ mode: z.enum(researchModes) });
export type ResearchSummary = z.infer<typeof summarySchema>;
export type ResearchState = {
  mode: typeof researchModes[number]; horizon: string; riskTolerance: string;
  stage: string; learningEnabled: boolean; summary?: string;
};
export const initialResearchState: ResearchState = {
  mode: '深度研究', horizon: '长期（1 年以上）', riskTolerance: '稳健', stage: 'idle', learningEnabled: false,
};
