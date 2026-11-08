import { authApiUrl } from "@/lib/auth-api";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const response = await fetch(`${authApiUrl()}/auth/google`, {
      cache: "no-store",
    });
    const body = (await response.json().catch(() => ({}))) as {
      enabled?: boolean;
    };
    return Response.json(
      { enabled: Boolean(body.enabled) },
      { status: response.ok ? 200 : response.status },
    );
  } catch {
    return Response.json({ enabled: false });
  }
}
