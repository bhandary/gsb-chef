const SESSION_COOKIE = "gsb_session";

function readCookie(header, name) {
  if (!header) return "";
  for (const part of header.split(";")) {
    const separator = part.indexOf("=");
    if (separator === -1) continue;
    const key = part.slice(0, separator).trim();
    if (key !== name) continue;
    const raw = part.slice(separator + 1).trim();
    try {
      return decodeURIComponent(raw);
    } catch {
      return raw;
    }
  }
  return "";
}

export async function authorizeAgentProxy({ cookieHeader, authApiUrl, fetchImpl }) {
  const token = readCookie(cookieHeader, SESSION_COOKIE);
  if (!token) {
    return { ok: false, status: 401, body: { error: "Sign in required." } };
  }
  let response;
  try {
    response = await fetchImpl(`${authApiUrl}/auth/me`, {
      headers: { authorization: `Bearer ${token}` },
    });
  } catch {
    return { ok: false, status: 401, body: { error: "Sign in required." } };
  }
  if (!response.ok) {
    return { ok: false, status: 401, body: { error: "Sign in required." } };
  }
  return { ok: true };
}
