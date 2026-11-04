#!/usr/bin/env node
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";

const require = createRequire(process.env.WEB_PACKAGE);
const { chromium } = require("@playwright/test");

const base = process.env.VERIFY_BASE_URL;
const email = process.env.VERIFY_EMAIL;
const password = process.env.VERIFY_PASSWORD;
const authLog = process.env.VERIFY_AUTH_LOG;
const evidence = process.env.VERIFY_EVIDENCE;

function write(name, value) {
  writeFileSync(`${evidence}/${name}`, value);
}

const browser = await chromium.launch({
  channel: "chrome",
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
try {
  await page.goto(base + "/", { waitUntil: "domcontentloaded" });
  await page.getByLabel("Email").waitFor({ timeout: 30000 });
  await page.screenshot({ path: `${evidence}/auth-screen.png`, fullPage: true });

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  const signupResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/auth/signup") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Create account" }).click();
  const response = await signupResponse;
  const signupBody = await response.json();
  write(
    "signup-response.json",
    JSON.stringify({ status: response.status(), body: signupBody }, null, 2) + "\n",
  );
  if (response.status() !== 201 || signupBody.delivery !== "log") {
    throw new Error(
      `Sign-up did not log a verification link: ${response.status()} ${JSON.stringify(signupBody)}`,
    );
  }
  await page.getByText(
    "Account created. Open the verification link printed in the auth server log.",
  ).waitFor({ timeout: 10000 });
  await page.screenshot({ path: `${evidence}/signup-notice.png`, fullPage: true });

  let link = "";
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const text = readFileSync(authLog, "utf8");
    const matches = [
      ...text.matchAll(/Verification link for (\S+): (\S+)/g),
    ].filter((match) => match[1] === email);
    if (matches.length) {
      link = matches[matches.length - 1][2];
      write("verification-log-line.txt", matches[matches.length - 1][0] + "\n");
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  if (!link.startsWith(base + "/verify#token=")) {
    throw new Error(`Auth log did not contain a verification link for ${email}`);
  }
  const token = new URL(link).hash.replace(/^#token=/, "");
  write("verification-token-sha256.txt", createHash("sha256").update(token).digest("hex") + "\n");

  await page.goto(link, { waitUntil: "domcontentloaded" });
  const chat = page.getByPlaceholder(
    "List leftover ingredients, for example rice, coconut, and curry leaves",
  );
  const invalid = page.getByText("This verification link is invalid.");
  const used = page.getByText("This verification link has already been used.");
  const expired = page.getByText("This verification link has expired.");
  const winner = await Promise.race([
    chat.waitFor({ timeout: 30000 }).then(() => "chat"),
    invalid.waitFor({ timeout: 30000 }).then(() => "invalid"),
    used.waitFor({ timeout: 30000 }).then(() => "used"),
    expired.waitFor({ timeout: 30000 }).then(() => "expired"),
  ]);
  if (winner !== "chat") {
    await page.screenshot({ path: `${evidence}/verify-failed.png`, fullPage: true });
    throw new Error(`Opening the logged verification link showed ${winner}.`);
  }
  await page.getByRole("button", { name: "API key settings" }).waitFor({ timeout: 5000 });
  await page.screenshot({ path: `${evidence}/verified-chat.png`, fullPage: true });

  const me = await page.request.get(base + "/api/auth/me");
  write(
    "me.json",
    JSON.stringify({ status: me.status(), body: await me.json() }, null, 2) + "\n",
  );
  const cookies = await page.context().cookies(base + "/");
  const session = cookies.find((cookie) => cookie.name === "gsb_session");
  if (!session?.value) {
    throw new Error("Verified session did not set the gsb_session cookie.");
  }
  write(
    "session-cookie-sha256.txt",
    createHash("sha256").update(session.value).digest("hex") + "\n",
  );
  write("verification-token-length.txt", String(token.length) + "\n");
} finally {
  await browser.close();
}
