import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { authorizeAgentProxy } from "@/lib/agent-proxy-auth.mjs";
import { SESSION_COOKIE, authApiUrl } from "@/lib/auth-api";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const decision = await authorizeAgentProxy({
    cookieHeader: request.headers.get("cookie"),
    authApiUrl: authApiUrl(),
    fetchImpl: fetch,
  });
  if (!decision.ok) {
    return NextResponse.json(decision.body, { status: decision.status });
  }
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ error: "Sign in required." }, { status: 401 });
  }
  let response: Response;
  try {
    response = await fetch(`${authApiUrl()}/feedback`, {
      method: "POST",
      cache: "no-store",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${token}`,
      },
      body: await request.text(),
    });
  } catch {
    return NextResponse.json(
      { error: "The account server is not running." },
      { status: 503 },
    );
  }
  const body = await response.json().catch(() => ({}));
  return NextResponse.json(body, { status: response.status });
}
