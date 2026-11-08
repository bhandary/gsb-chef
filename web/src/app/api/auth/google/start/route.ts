import { NextResponse } from "next/server";

import { authApiUrl } from "@/lib/auth-api";

export const dynamic = "force-dynamic";

function httpUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    return url.toString();
  } catch {
    return null;
  }
}

export async function GET() {
  let response: Response;
  try {
    response = await fetch(`${authApiUrl()}/auth/google/start`, {
      cache: "no-store",
      headers: { accept: "application/json" },
    });
  } catch {
    return Response.json(
      { error: "The account server is not running." },
      { status: 503 },
    );
  }
  const body = (await response.json().catch(() => ({}))) as { url?: unknown };
  const url = httpUrl(body.url);
  if (!response.ok || !url) {
    return Response.json(
      { error: "Google sign-in is not configured." },
      { status: response.status || 404 },
    );
  }
  return NextResponse.redirect(url);
}
