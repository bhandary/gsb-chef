import { createRequire } from "node:module";
import { writeFileSync } from "node:fs";

const require = createRequire(process.env.WEB_PACKAGE);
const { chromium } = require("@playwright/test");

const base = process.env.VERIFY_BASE_URL;
const email = process.env.VERIFY_EMAIL;
const password = process.env.VERIFY_PASSWORD;
const evidence = process.env.VERIFY_EVIDENCE;
const placeholder =
  "List leftover ingredients, for example rice, coconut, and curry leaves";
const replyText = "Seeded reply for feedback.";

function write(name, value) {
  writeFileSync(`${evidence}/${name}`, value);
}

async function seedThread() {
  const threadId = crypto.randomUUID();
  const assistantId = crypto.randomUUID();
  const create = await fetch("http://127.0.0.1:2024/threads", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      thread_id: threadId,
      metadata: { graph_id: "agent" },
    }),
  });
  if (!create.ok) {
    throw new Error(`Creating the thread failed: ${create.status} ${await create.text()}`);
  }
  const state = await fetch(`http://127.0.0.1:2024/threads/${threadId}/state`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      values: {
        messages: [
          { id: crypto.randomUUID(), type: "human", content: "rice and coconut" },
          { id: assistantId, type: "ai", content: replyText },
        ],
      },
    }),
  });
  if (!state.ok) {
    throw new Error(`Seeding the reply failed: ${state.status} ${await state.text()}`);
  }
  const run = await fetch(`http://127.0.0.1:2024/threads/${threadId}/runs/wait`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      assistant_id: "agent",
      input: { messages: [{ type: "human", content: "also curry leaves" }] },
    }),
  });
  const runBody = await run.json().catch(() => ({}));
  const historyResponse = await fetch(`http://127.0.0.1:2024/threads/${threadId}/history`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ limit: 10 }),
  });
  const history = await historyResponse.json();
  const stamped = (Array.isArray(history) ? history : []).find(
    (item) =>
      item?.metadata?.run_id &&
      (item?.values?.messages || []).some(
        (message) => message?.id === assistantId && message?.type === "ai",
      ),
  );
  if (!stamped?.metadata?.run_id) {
    throw new Error("No checkpoint with the seeded reply has a run id.");
  }
  return {
    threadId,
    assistantId,
    runId: stamped.metadata.run_id,
    runStatus: run.status,
    runError: runBody?.__error__?.message || null,
  };
}

const browser = await chromium.launch({
  channel: "chrome",
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
let posts = 0;
let cookiePresent = false;
let traceIdSent = "";

try {
  await page.goto(base + "/", { waitUntil: "domcontentloaded" });
  await page.getByLabel("Email").waitFor({ timeout: 30000 });
  const mode = page.getByRole("button", { name: "Sign in", exact: true });
  if ((await mode.count()) !== 1) {
    throw new Error(`Expected one Sign in mode button before submit, saw ${await mode.count()}.`);
  }
  await mode.click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.locator('button[type="submit"]').click();
  const chat = page.getByPlaceholder(placeholder);
  const unverified = page.getByText("Verify your email before signing in.");
  const landed = await Promise.race([
    chat.waitFor({ timeout: 30000 }).then(() => "chat"),
    unverified.waitFor({ timeout: 30000 }).then(() => "unverified"),
  ]);
  if (landed !== "chat") {
    throw new Error("Sign-in did not open the chat. Run drive-signup.sh on this launch first.");
  }

  const seeded = await seedThread();
  write("feedback-seed.json", JSON.stringify(seeded, null, 2) + "\n");

  await page.route("**/api/feedback", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    posts += 1;
    const headers = await route.request().allHeaders();
    cookiePresent = (headers.cookie || "").includes("gsb_session=");
    traceIdSent = JSON.parse(route.request().postData() || "{}").trace_id || "";
    if (posts === 1) {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, logged: true }),
    });
  });

  await page.goto(`${base}/?threadId=${seeded.threadId}`, { waitUntil: "domcontentloaded" });
  await page.getByText(replyText).waitFor({ timeout: 30000 });
  const up = page.getByRole("button", { name: "Thumbs up", exact: true });
  const down = page.getByRole("button", { name: "Thumbs down", exact: true });
  await up.waitFor({ timeout: 15000 });
  await down.waitFor({ timeout: 5000 });
  if ((await up.getAttribute("aria-pressed")) !== "false") {
    throw new Error("Thumbs up started pressed.");
  }
  if ((await down.getAttribute("aria-pressed")) !== "false") {
    throw new Error("Thumbs down started pressed.");
  }
  await page.screenshot({ path: `${evidence}/feedback-unpressed.png`, fullPage: true });

  const firstResponse = page.waitForResponse(
    (response) => response.url().includes("/api/feedback") && response.request().method() === "POST",
  );
  await up.click();
  const response = await firstResponse;
  const responseBody = await response.json();
  if (response.status() !== 503 || responseBody.error !== "feedback not configured") {
    throw new Error(`Unexpected feedback response: ${response.status()} ${JSON.stringify(responseBody)}`);
  }
  if (traceIdSent !== seeded.runId) {
    throw new Error(`trace_id ${traceIdSent} did not match run id ${seeded.runId}`);
  }
  if (!cookiePresent) {
    throw new Error("POST /api/feedback did not include the gsb_session cookie.");
  }
  await page.getByText("Could not save feedback").waitFor({ timeout: 5000 });
  if ((await up.getAttribute("aria-pressed")) !== "false") {
    throw new Error("Thumbs up stayed pressed after feedback was not configured.");
  }
  await page.screenshot({ path: `${evidence}/feedback-unconfigured.png`, fullPage: true });

  await up.click();
  await page.waitForTimeout(300);
  if ((await up.getAttribute("aria-pressed")) !== "true") {
    throw new Error("A logged feedback response did not keep Thumbs up pressed.");
  }
  await page.screenshot({ path: `${evidence}/feedback-pressed.png`, fullPage: true });

  const postsBeforeClear = posts;
  await up.click();
  await page.waitForTimeout(400);
  if (posts !== postsBeforeClear) {
    throw new Error("Clearing the selected thumb sent another /api/feedback request.");
  }
  if ((await up.getAttribute("aria-pressed")) !== "false") {
    throw new Error("Clearing the selected thumb left it pressed.");
  }

  const signedOut = await fetch(base + "/api/feedback", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ reaction: "liked", trace_id: seeded.runId }),
  });
  const signedOutBody = await signedOut.json();
  if (signedOut.status !== 401 || signedOutBody.error !== "Sign in required.") {
    throw new Error(`Signed-out feedback returned ${signedOut.status} ${JSON.stringify(signedOutBody)}`);
  }

  write(
    "feedback-proof.txt",
    [
      "feedback PASS",
      `thread ${seeded.threadId}`,
      `trace_id ${seeded.runId}`,
      "unconfigured 503",
      "session cookie present",
      "pressed after fulfilled 200",
      "clear sent no request",
      "signed out 401",
      "",
    ].join("\n"),
  );
  console.log("FEEDBACK PROOF PASS");
  console.log(`${evidence}/feedback-proof.txt`);
} finally {
  await browser.close();
}
