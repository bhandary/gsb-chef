import assert from "node:assert/strict";
import test from "node:test";

import { authorizeAgentProxy } from "./agent-proxy-auth.mjs";

test("agent proxy rejects a request with no session cookie", async () => {
  let called = false;
  const decision = await authorizeAgentProxy({
    cookieHeader: "other=1",
    authApiUrl: "http://127.0.0.1:8000",
    fetchImpl: async () => {
      called = true;
      return { ok: true };
    },
  });
  assert.equal(called, false);
  assert.deepEqual(decision, {
    ok: false,
    status: 401,
    body: { error: "Sign in required." },
  });
});

test("agent proxy rejects a session the auth server does not accept", async () => {
  const decision = await authorizeAgentProxy({
    cookieHeader: "gsb_session=stale-token",
    authApiUrl: "http://127.0.0.1:8000",
    fetchImpl: async (url, init) => {
      assert.equal(url, "http://127.0.0.1:8000/auth/me");
      assert.equal(init.headers.authorization, "Bearer stale-token");
      return { ok: false };
    },
  });
  assert.equal(decision.ok, false);
  assert.equal(decision.status, 401);
});

test("agent proxy allows a session the auth server accepts", async () => {
  const decision = await authorizeAgentProxy({
    cookieHeader: "theme=light; gsb_session=live-token",
    authApiUrl: "http://127.0.0.1:8000",
    fetchImpl: async (_url, init) => {
      assert.equal(init.headers.authorization, "Bearer live-token");
      return { ok: true };
    },
  });
  assert.deepEqual(decision, { ok: true });
});

test("agent proxy fails closed when the auth server cannot be reached", async () => {
  const decision = await authorizeAgentProxy({
    cookieHeader: "gsb_session=live-token",
    authApiUrl: "http://127.0.0.1:8000",
    fetchImpl: async () => {
      throw new Error("connect ECONNREFUSED");
    },
  });
  assert.equal(decision.ok, false);
  assert.equal(decision.status, 401);
});
