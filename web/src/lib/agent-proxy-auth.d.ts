export function authorizeAgentProxy(input: {
  cookieHeader: string | null;
  authApiUrl: string;
  fetchImpl: (
    input: string,
    init?: { headers?: Record<string, string> },
  ) => Promise<{ ok: boolean }>;
}): Promise<
  { ok: true } | { ok: false; status: number; body: { error: string } }
>;
