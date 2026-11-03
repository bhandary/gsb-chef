export const SESSION_COOKIE = "gsb_session";
const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 14;

export function authApiUrl(): string {
  return process.env.AUTH_API_URL || "http://127.0.0.1:8000";
}

export function sessionCookieOptions() {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  };
}
