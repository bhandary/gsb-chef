import { cookies } from "next/headers";
import { SESSION_COOKIE, authApiUrl, sessionCookieOptions } from "@/lib/auth-api";

export const dynamic = "force-dynamic";

async function proxy(
  path: string,
  init?: RequestInit,
): Promise<{ status: number; body: Record<string, unknown> }> {
  let response: Response;
  try {
    response = await fetch(`${authApiUrl()}${path}`, {
      ...init,
      cache: "no-store",
      headers: {
        "content-type": "application/json",
        ...(init?.headers || {}),
      },
    });
  } catch {
    return {
      status: 503,
      body: { error: "The account server is not running." },
    };
  }
  const body = (await response.json().catch(() => ({}))) as Record<
    string,
    unknown
  >;
  return { status: response.status, body };
}

async function setSession(token: string) {
  const jar = await cookies();
  jar.set(SESSION_COOKIE, token, sessionCookieOptions());
}

async function clearSession() {
  const jar = await cookies();
  jar.set(SESSION_COOKIE, "", { ...sessionCookieOptions(), maxAge: 0 });
}

export async function POST(
  request: Request,
  context: { params: Promise<{ action: string }> },
) {
  const { action } = await context.params;
  if (action === "logout") {
    const jar = await cookies();
    const token = jar.get(SESSION_COOKIE)?.value;
    if (token) {
      await proxy("/auth/logout", {
        method: "POST",
        headers: { authorization: `Bearer ${token}` },
      });
    }
    await clearSession();
    return Response.json({ ok: true });
  }

  const payload = await request.text();
  if (action === "signup") {
    const result = await proxy("/auth/signup", { method: "POST", body: payload });
    return Response.json(result.body, { status: result.status });
  }
  if (action === "login" || action === "verify") {
    const result = await proxy(`/auth/${action}`, {
      method: "POST",
      body: payload,
    });
    const token = result.body.token;
    if (result.status < 400 && typeof token === "string") {
      await setSession(token);
      const { token: _token, ...safe } = result.body;
      return Response.json(safe, { status: result.status });
    }
    return Response.json(result.body, { status: result.status });
  }
  return Response.json({ error: "Not found." }, { status: 404 });
}

export async function GET(
  _request: Request,
  context: { params: Promise<{ action: string }> },
) {
  const { action } = await context.params;
  if (action !== "me") {
    return Response.json({ error: "Not found." }, { status: 404 });
  }
  const jar = await cookies();
  const token = jar.get(SESSION_COOKIE)?.value;
  if (!token) {
    return Response.json({ error: "Sign in required." }, { status: 401 });
  }
  const result = await proxy("/auth/me", {
    method: "GET",
    headers: { authorization: `Bearer ${token}` },
  });
  if (result.status === 401) {
    await clearSession();
  }
  return Response.json(result.body, { status: result.status });
}
