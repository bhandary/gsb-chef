import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { initApiPassthrough } from "langgraph-nextjs-api-passthrough";

import { authorizeAgentProxy } from "@/lib/agent-proxy-auth.mjs";

// Proxies same-origin /api requests to the recipe server after a session check.

const passthrough = initApiPassthrough({
  apiUrl: process.env.LANGGRAPH_API_URL ?? "remove-me", // default, if not defined it will attempt to read process.env.LANGGRAPH_API_URL
  apiKey: process.env.LANGSMITH_API_KEY ?? "remove-me", // default, if not defined it will attempt to read process.env.LANGSMITH_API_KEY
  runtime: "edge", // default
  disableWarningLog: true,
});

type Handler = (req: NextRequest) => Promise<Response> | Response;

async function guarded(request: NextRequest, handler: Handler) {
  const decision = await authorizeAgentProxy({
    cookieHeader: request.headers.get("cookie"),
    authApiUrl: process.env.AUTH_API_URL || "http://127.0.0.1:8000",
    fetchImpl: fetch,
  });
  if (!decision.ok) {
    return NextResponse.json(decision.body, { status: decision.status });
  }
  return handler(request);
}

export const GET = (request: NextRequest) => guarded(request, passthrough.GET);
export const POST = (request: NextRequest) => guarded(request, passthrough.POST);
export const PUT = (request: NextRequest) => guarded(request, passthrough.PUT);
export const PATCH = (request: NextRequest) => guarded(request, passthrough.PATCH);
export const DELETE = (request: NextRequest) =>
  guarded(request, passthrough.DELETE);
export const OPTIONS = passthrough.OPTIONS;
export const runtime = "edge";
