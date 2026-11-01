import { APICallError, jsonSchema, streamText, tool, type ModelMessage, type ToolSet } from 'ai';
import { createOpenAICompatible } from '@ai-sdk/openai-compatible';
import { z } from 'zod';
import { internalAuthorized } from '../../../../lib/folio-session';

export const runtime = 'nodejs';
export const maxDuration = 120;
const requestSchema = z.object({
  messages: z.array(z.record(z.string(), z.unknown())).min(1).max(120),
  tools: z.array(z.object({ name: z.string().regex(/^[a-zA-Z0-9_-]{1,80}$/), description: z.string().max(4000).optional(), parameters: z.record(z.string(), z.unknown()) })).max(32).default([]),
});
export async function POST(request: Request) {
  if (!internalAuthorized(request)) return Response.json({ error: 'Unauthorized' }, { status: 401 });
  if (Number(request.headers.get('content-length') ?? 0) > 512_000) return Response.json({ error: 'Request too large' }, { status: 413 });
  const raw = await request.text();
  if (raw.length > 512_000) return Response.json({ error: 'Request too large' }, { status: 413 });
  let parsed;
  try { parsed = requestSchema.safeParse(JSON.parse(raw)); }
  catch { return Response.json({ error: 'Invalid JSON' }, { status: 400 }); }
  if (!parsed.success) return Response.json({ error: 'Invalid model request' }, { status: 400 });
  const apiKey = process.env.DASHSCOPE_API_KEY?.trim();
  if (!apiKey) return Response.json({ error: 'DashScope 未配置：请在项目 Vars 中添加 DASHSCOPE_API_KEY。' }, { status: 503 });
  const dashscope = createOpenAICompatible({
    name: 'dashscope',
    apiKey,
    baseURL: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  });
  const tools: ToolSet = Object.fromEntries(parsed.data.tools.map(spec => [spec.name, tool({ description: spec.description, inputSchema: jsonSchema(spec.parameters) })]));
  const result = streamText({
    model: dashscope.chatModel('qwen3.8-flash'),
    messages: parsed.data.messages as ModelMessage[],
    tools,
    maxOutputTokens: 2400,
    abortSignal: request.signal,
  });
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        for await (const part of result.fullStream) {
          if (part.type === 'text-delta') controller.enqueue(encoder.encode(`${JSON.stringify({ type: 'text', text: part.text })}\n`));
          if (part.type === 'tool-call') controller.enqueue(encoder.encode(`${JSON.stringify({ type: 'tool_call', id: part.toolCallId, name: part.toolName, args: part.input })}\n`));
          if (part.type === 'error') throw part.error;
        }
      } catch (error) {
        const status = APICallError.isInstance(error) ? error.statusCode : undefined;
        const message = status === 401 || status === 403
          ? 'DashScope 鉴权失败：请检查 API Key、北京地域及模型访问权限。'
          : status === 404
            ? 'DashScope 模型不可用：请确认当前账号可以访问 qwen3.8-flash。'
            : status === 429
              ? 'DashScope 请求受限：请检查百炼额度或稍后重试。'
              : 'DashScope 模型调用暂不可用，请稍后重试。';
        controller.enqueue(encoder.encode(`${JSON.stringify({ type: 'error', message })}\n`));
      } finally { controller.close(); }
    },
  });
  return new Response(stream, { headers: { 'Content-Type': 'application/x-ndjson', 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no' } });
}
