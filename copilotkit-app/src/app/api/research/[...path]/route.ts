import { NextRequest } from "next/server";

// Only report/data operations; no generic URL proxy and no credential forwarding.
async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (!/^(reports(?:\/[a-f0-9-]+(?:\/export\/(?:md|json|pdf))?)?|status|market-review|market-sentiment|market-follow-through|market-industry-history|a-share-events|review-candidates(?:\/[0-9]{6}\.(?:SH|SZ))?|review-checks(?:\/[a-f0-9-]+(?:\/verify)?)?|followups|tasks(?:\/[a-f0-9-]+)?|schedules(?:\/[a-f0-9-]+(?:\/(?:run|history))?)?|settings(?:\/(?:ai|data))?)$/.test(path.join("/"))) {
    return Response.json({ error: "Unknown research endpoint" }, { status: 404 });
  }
  const hasBody = request.method === "POST" || request.method === "PUT";
  if (hasBody && request.headers.get("content-type")?.split(";")[0] !== "application/json") {
    return Response.json({ error: "需要 JSON 请求。" }, { status: 415 });
  }
  const base = process.env.AGENT_URL || process.env.LANGGRAPH_DEPLOYMENT_URL || "http://127.0.0.1:8123";
  try {
    const upstream = await fetch(`${base.replace(/\/$/, "")}/research/${path.join("/")}${request.nextUrl.search}`, {
      method: request.method, cache: "no-store", signal: request.signal,
      ...(hasBody ? {
        body: await request.text(), headers: { "Content-Type": "application/json" },
      } : {}),
    });
    const headers = new Headers();
    for (const name of ["content-type", "content-disposition"]) {
      const value = upstream.headers.get(name);
      if (value) headers.set(name, value);
    }
    headers.set("Cache-Control", "no-store");
    headers.set("X-Content-Type-Options", "nosniff");
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch {
    return Response.json({ error: "研究服务暂不可用，请确认 FastAPI 服务已启动。" }, { status: 503 });
  }
}

export const GET = proxy;
export const DELETE = proxy;
export const POST = proxy;
export const PUT = proxy;
