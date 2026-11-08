import { NextRequest } from "next/server";

// Fixed research/settings endpoints, including server-side provider configuration.
async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const route = path.join("/");
  const evaluationRoute = /^evaluations\/(?:datasets(?:\/import|\/[a-f0-9-]+(?:\/(?:publish|archive|restore|export))?)?|versions\/[a-f0-9-]+|runs(?:\/[a-f0-9-]+(?:\/(?:cancel|retry|export|attempts\/[a-f0-9-]+))?)?|compare)$/.test(route);
  const knowledgeRoute = /^knowledge\/(?:collections(?:\/[a-f0-9-]+(?:\/(?:members|archive|restore|history|calculations|figures(?:\/[a-f0-9-]+\/(?:archive|restore))?|figure-context\/[a-f0-9-]+\/K[1-9][0-9]*))?)?|conversations(?:\/[a-f0-9-]+)?|scope|embedding(?:\/test)?|indices|search|searches\/[a-f0-9-]+)$/.test(route);
  const graphRoute = /^graphs(?:\/[a-f0-9-]+(?:\/(?:archive|restore|history|sync|extractions(?:\/(?:preview|[a-f0-9-]+))?|extracted-candidates(?:\/[a-f0-9-]+(?:\/(?:resolve|reject))?)?|query|queries(?:\/[a-f0-9-]+)?|entities(?:\/[a-f0-9-]+(?:\/(?:archive|restore))?)?|relations(?:\/[a-f0-9-]+(?:\/review)?)?))?)?$/.test(route);
  if (!/^(documents(?:\/(?:upload|import|options|imports\/[a-f0-9-]+\/retry|[a-f0-9-]+(?:\/(?:archive|restore|retry|history|download|(?:pages|preview)\/[0-9]+))?))?|reports(?:\/[a-f0-9-]+(?:\/export\/(?:md|json|pdf))?)?|report-comparisons|status|market-review|market-sentiment|market-follow-through|market-industry-history|a-share-events|review-candidates(?:\/[0-9]{6}\.(?:SH|SZ))?|review-checks(?:\/[a-f0-9-]+(?:\/verify)?)?|followups|tasks(?:\/[a-f0-9-]+(?:\/cancel)?)?|schedules(?:\/[a-f0-9-]+(?:\/(?:run|history))?)?|settings(?:\/(?:ai(?:\/test)?|data))?)$/.test(route)) {
    if (!knowledgeRoute && !graphRoute && !evaluationRoute) return Response.json({ error: "Unknown research endpoint" }, { status: 404 });
  }
  const hasBody = request.method === "POST" || request.method === "PUT";
  const upload = route === "documents/upload" && request.method === "POST";
  const contentType = request.headers.get("content-type") || "";
  if (upload && !contentType.startsWith("multipart/form-data;")) {
    return Response.json({ error: "A multipart file upload is required." }, { status: 415 });
  }
  if (hasBody && !upload && contentType.split(";")[0] !== "application/json") {
    return Response.json({ error: "需要 JSON 请求。" }, { status: 415 });
  }
  const base = process.env.AGENT_URL || process.env.LANGGRAPH_DEPLOYMENT_URL || "http://127.0.0.1:8123";
  try {
    const headers = new Headers();
    if (hasBody) headers.set("Content-Type", upload ? contentType : "application/json");
    const origin = request.headers.get("origin");
    if (origin) headers.set("Origin", origin);
    const options: RequestInit & { duplex?: "half" } = {
      method: request.method, cache: "no-store", signal: request.signal,
      headers,
      ...(hasBody ? upload ? { body: request.body, duplex: "half" } : { body: await request.text() } : {}),
    };
    const upstream = await fetch(`${base.replace(/\/$/, "")}/research/${route}${request.nextUrl.search}`, options);
    const resultHeaders = new Headers();
    for (const name of ["content-type", "content-disposition"]) {
      const value = upstream.headers.get(name);
      if (value) resultHeaders.set(name, value);
    }
    resultHeaders.set("Cache-Control", "no-store");
    resultHeaders.set("X-Content-Type-Options", "nosniff");
    return new Response(upstream.body, { status: upstream.status, headers: resultHeaders });
  } catch {
    return Response.json({ error: "研究服务暂不可用，请确认 FastAPI 服务已启动。" }, { status: 503 });
  }
}

export const GET = proxy;
export const DELETE = proxy;
export const POST = proxy;
export const PUT = proxy;
