import { jsonSchema, streamText, tool, type ModelMessage, type ToolSet } from 'ai';
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
  const tools: ToolSet = Object.fromEntries(parsed.data.tools.map(spec => [spec.name, tool({ description: spec.description, inputSchema: jsonSchema(spec.parameters) })]));
  const result = streamText({
    model: 'anthropic/claude-sonnet-5.5',
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
          if (part.type === 'error') {
            const message = part.error instanceof Error ? part.error.message : '';
            throw new Error(/valid credit card|customer_verification_required/i.test(message)
              ? 'AI Gateway 需要团队添加银行卡完成验证后才能调用模型。请在 Vercel 团队的 AI Gateway 设置中完成验证后重试。'
              : '模型调用暂不可用，请稍后重试。');
          }
        }
      } catch (error) {
        const message = error instanceof Error && error.message.startsWith('AI Gateway 需要') ? error.message : '模型调用暂不可用，请稍后重试。';
        controller.enqueue(encoder.encode(`${JSON.stringify({ type: 'error', message })}\n`));
      } finally { controller.close(); }
    },
  });
  return new Response(stream, { headers: { 'Content-Type': 'application/x-ndjson', 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no' } });
}
