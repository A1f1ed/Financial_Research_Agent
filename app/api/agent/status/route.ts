export const dynamic = 'force-dynamic';
export async function GET() {
  const configured = Boolean(process.env.CPK_INTELLIGENCE_API_KEY && process.env.FOLIO_INTERNAL_SECRET && process.env.FOLIO_SESSION_SECRET);
  let python = false;
  let financialData = false;
  if (configured) {
    try {
      const response = await fetch(`${process.env.PYTHON_AGENT_URL ?? 'http://localhost:8000'}/health`, { cache: 'no-store', signal: AbortSignal.timeout(3000) });
      const status = response.ok ? await response.json() : null;
      python = status?.agent === 'folio_research';
      financialData = python && status.financialData === true;
    } catch { python = false; }
  }
  return Response.json({ configured, python, cloudConfigured: Boolean(process.env.CPK_INTELLIGENCE_API_KEY), learning: 'opt-in', financialData }, { headers: { 'Cache-Control': 'no-store' } });
}
