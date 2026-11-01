import { getCopilotHandler } from '../../../../lib/copilot-runtime';
import { sameOrigin, userFromRequest } from '../../../../lib/folio-session';

export const runtime = 'nodejs';
export const maxDuration = 300;
export const dynamic = 'force-dynamic';
async function handle(request: Request) {
  if (!sameOrigin(request)) return Response.json({ error: 'Invalid request origin.' }, { status: 403 });
  try { userFromRequest(request); }
  catch { return Response.json({ error: '请刷新页面以创建安全工作空间会话。' }, { status: 401 }); }
  try { return await getCopilotHandler()(request); }
  catch { return Response.json({ error: 'CopilotKit Runtime 暂不可用，请检查云项目与 Python Agent 配置。' }, { status: 503 }); }
}
export { handle as GET, handle as POST, handle as DELETE, handle as OPTIONS };
