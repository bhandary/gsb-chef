import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE, authApiUrl, sessionCookieOptions } from "@/lib/auth-api";

export const dynamic = "force-dynamic";

function safeMessage(value: unknown): string {
  if (typeof value !== "string") return "Google sign-in failed.";
  const trimmed = value.trim();
  if (
    !trimmed ||
    trimmed.length > 200 ||
    /[\r\n]/.test(trimmed) ||
    trimmed.includes("eyJ")
  ) {
    return "Google sign-in failed.";
  }
  return trimmed;
}

function loginError(request: NextRequest, message: string) {
  const dest = new URL("/login", request.url);
  dest.searchParams.set("google_error", message);
  return NextResponse.redirect(dest);
}

export async function GET(request: NextRequest) {
  if (request.nextUrl.searchParams.get("error")) {
    return loginError(request, "Google sign-in was cancelled.");
  }
  const code = request.nextUrl.searchParams.get("code");
  const state = request.nextUrl.searchParams.get("state");
  if (!code || !state) {
    return loginError(
      request,
      "Google sign-in could not be verified. Start again.",
    );
  }
  let upstream: Response;
  try {
    upstream = await fetch(`${authApiUrl()}/auth/google/callback`, {
      method: "POST",
      cache: "no-store",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ code, state }),
    });
  } catch {
    return loginError(request, "The account server is not running.");
  }
  const payload = (await upstream.json().catch(() => ({}))) as {
    token?: unknown;
    error?: unknown;
  };
  if (!upstream.ok || typeof payload.token !== "string" || !payload.token) {
    return loginError(request, safeMessage(payload.error));
  }
  const response = NextResponse.redirect(new URL("/", request.url));
  response.cookies.set(SESSION_COOKIE, payload.token, sessionCookieOptions());
  return response;
}
