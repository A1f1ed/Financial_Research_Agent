import { getIntelligence } from '../../../../lib/copilot-runtime';
import { AGENT_ID } from '../../../../lib/folio-contract';
import { userFromRequest } from '../../../../lib/folio-session';

export const dynamic = 'force-dynamic';
export async function GET(request: Request) {
  let user;
  try { user = userFromRequest(request); }
  catch { return Response.json({ error: '请刷新页面以创建工作空间会话。' }, { status: 401 }); }
  try {
    const result = await getIntelligence().listThreads({ userId: user.id, agentId: AGENT_ID, limit: 50 });
    return Response.json({ threads: result.threads }, { headers: { 'Cache-Control': 'no-store' } });
  } catch {
    return Response.json({ error: '无法读取云端会话，请稍后重试。' }, { status: 503 });
  }
}
