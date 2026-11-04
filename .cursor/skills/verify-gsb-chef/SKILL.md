---
name: verify-gsb-chef
description: Drive the real gsb-chef app and prove behavior with evidence. The surface is the browser chat UI in web/, backed by the langgraph dev server and the auth_app sign-up server. Use when a change can affect sign-up, email verification, the session gate, the chef chat, the gear-menu API keys, or the missing-key error, and when you need a recorded browser path instead of a unit test.
---

# Verify gsb-chef

Drive the running app the way a user does. The product commands are in the root `README.md`: `python -m auth_app`, `langgraph dev`, and `cd web && pnpm dev`. The scripts below pin the host, port, empty database, and log delivery so a proof does not share the repo `data/auth.db` and does not send mail.

Keep this map current with `/maintain-verification-skill`.

## Side by side

Two instances cannot run side by side.

- The auth server listens on `127.0.0.1:8000` (`AUTH_HOST`, `AUTH_PORT`). The UI proxies to it with `AUTH_API_URL=http://127.0.0.1:8000` from `web/.env`.
- `langgraph dev` listens on `127.0.0.1:2024`. The browser calls `NEXT_PUBLIC_API_URL=http://localhost:2024` and `NEXT_PUBLIC_ASSISTANT_ID=agent`.
- The Next dev server listens on `127.0.0.1:3000`.
- `langgraph dev` stores its local API state in the repo-root `.langgraph_api` directory. A second dev server in this checkout uses that same directory.
- `GSB_AUTH_DB` can point at another SQLite file, and this skill does that, but the UI still calls port 8000. A second database does not make a second instance.

`scripts/launch.sh` exits if any of those three ports already has a listener. Stop the instance this skill started with `scripts/cleanup.sh` before launching again. Do not kill whatever else is bound to those ports by process name.

## Launch

From the repo root, with `.venv` and `web/node_modules` already installed (`README.md` setup):

```bash
bash .cursor/skills/verify-gsb-chef/scripts/launch.sh
```

The script creates `verification-runs/<UTC stamp>/` with an empty `data/` directory. It does not copy or delete `data/auth.db`. `auth.py` creates the schema on the first connection. The script then starts three process groups with bash job control (`set -m`), so each background PID is the process-group id:

```bash
SMTP_HOST= SMTP_PASSWORD= APP_BASE_URL=http://127.0.0.1:3000 \
  GSB_AUTH_DB="$RUN/data/auth.db" AUTH_HOST=127.0.0.1 AUTH_PORT=8000 \
  .venv/bin/python -m auth_app

LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false \
  .venv/bin/langgraph dev --no-browser --host 127.0.0.1 --port 2024

cd web
NEXT_PUBLIC_API_URL=http://localhost:2024 NEXT_PUBLIC_ASSISTANT_ID=agent \
  AUTH_API_URL=http://127.0.0.1:8000 \
  ./node_modules/.bin/next dev --hostname 127.0.0.1 --port 3000
```

`SMTP_HOST` is set empty in the auth process environment. `python-dotenv` does not override an existing variable, so a Resend host in the root `.env` is not used. Empty `SMTP_HOST` makes `send_verification_email` log the link and return `"log"`. This launch does not start a real SMTP session.

`APP_BASE_URL=http://127.0.0.1:3000` makes the logged link `http://127.0.0.1:3000/verify#token=...`. `web/next.config.mjs` allows the dev origin `127.0.0.1`, which is required for the page to hydrate at that host.

READY means the app is usable, not only that a process answered. `launch.sh` waits until all of these are true, then opens Chrome and waits until the Email field and the Create account button are visible:

- `GET http://127.0.0.1:8000/auth/me` returns 401 and `{"error":"Sign in required."}`. `curl -f` treats 401 as failure; check the status code.
- `GET http://127.0.0.1:2024/ok` returns 200 and `{"ok":true,...}`.
- `POST http://127.0.0.1:2024/assistants/search` with `{}` returns a row whose `graph_id` and `name` are `agent`.
- `GET http://127.0.0.1:3000/` returns 200 and the body contains `<title>GSB Chef</title>`.
- `GET http://127.0.0.1:3000/api/auth/me` returns 401 and `{"error":"Sign in required."}`.
- Playwright, using Chrome, sees the label `Email` and the button `Create account` at `http://127.0.0.1:3000/`.
- `users`, `email_verification_tokens`, and `sessions` are empty. `auth.py` creates `auth.db` on the first `connect()`. A bearer-less `GET /auth/me` returns 401 before that. `GET /auth/me` with a `gsb_session` cookie does open the file and still leaves the tables empty when the session is unknown. Zero rows is the empty instance.

The script prints `READY` and the run directory. It writes `verification-runs/current` as a symlink to that directory and `instance.json` with the git HEAD, process-group ids, log paths, and `GSB_AUTH_DB`.

If launch fails after it has started a process, it runs `scripts/cleanup.sh` for those groups. Logs stay in the run directory.

Teardown is `scripts/cleanup.sh`. It signals those process groups and leaves the run directory in place.

## Doctor

Run this before driving whenever something looks off. It only reads process state, git HEAD, listeners, and HTTP responses.

```bash
bash .cursor/skills/verify-gsb-chef/scripts/doctor.sh
```

It passes only when:

- `verification-runs/current/instance.json` exists.
- `git rev-parse HEAD` equals the HEAD recorded at launch.
- Each recorded process-group leader is alive.
- Listeners on 8000, 2024, and 3000 are that launch's auth, langgraph, and web groups. Ownership is the process group or a parent pid, from `/proc`, not the process name.
- The auth, langgraph, web, and `/api/auth/me` checks from Launch still hold.

A passing doctor prints `DOCTOR OK`. Anything else prints `DOCTOR FAIL` and exits 1. Do not drive a `DOCTOR FAIL` instance.

## Drive

The browser is Playwright `1.64.1` from `web/node_modules/@playwright/test`, launched as installed Chrome:

```javascript
chromium.launch({ channel: "chrome", args: ["--no-sandbox", "--disable-dev-shm-usage"] })
```

Resolve the package from the UI project, because the skill directory has no `node_modules`:

```javascript
import { createRequire } from "node:module";
const { chromium } = createRequire(process.env.WEB_PACKAGE)("@playwright/test");
```

Set `WEB_PACKAGE` to `<repo>/web/package.json`. Open `http://127.0.0.1:3000/`. Wait for the label `Email` before touching the page. The first server render is the text `Loading…` until the client hydrates.

Stable handles:

| What the user sees | Handle |
| --- | --- |
| Email field | label `Email`, id `email` |
| Password field | label `Password`, id `password` |
| Sign-up mode | button `Sign up` |
| Sign-in mode | button `Sign in` |
| Submit a new account | button `Create account` |
| Submit an existing account | button `Sign in` (the submit button; the mode button has the same name, so prefer `Create account` for sign-up) |
| In-flight submit | button `Please wait` |
| Log delivery notice | text `Account created. Open the verification link printed in the auth server log.` |
| SMTP delivery notice | text `Account created. Open the verification link in your email.` |
| Unverified sign-in | text `Verify your email before signing in.` |
| Verification page | route `/verify#token=` then the page strips the hash |
| Chat composer | placeholder `List leftover ingredients, for example rice, coconut, and curry leaves` |
| Send | button `Send` |
| Gear menu | button `API key settings` |
| Key dialog heading | heading `Recipe API keys` |
| OpenAI field | label `OpenAI API key`, id `openai` |
| Tavily field | label `Tavily API key`, id `tavily` |
| Save keys | button `Save` |
| Dismiss the dialog | button `Cancel` |
| End the session | button `Sign out` |

Routes the browser actually uses: `/`, `/verify`, `POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/verify`, `POST /api/auth/logout`, `GET /api/auth/me`. The Next handlers proxy to `http://127.0.0.1:8000/auth/signup`, `/auth/login`, `/auth/verify`, `/auth/logout`, and `/auth/me`. The session cookie is `gsb_session`, httpOnly, so `document.cookie` does not show it. Read it from the Playwright cookie jar.

The sign-up journey is one command:

```bash
bash .cursor/skills/verify-gsb-chef/scripts/drive-signup.sh
```

It uses `gsb-verify@example.com` and `verify-skill-pass` unless `VERIFY_EMAIL` and `VERIFY_PASSWORD` are set. It refuses to run when that database already has a user, token, or session row. The other feature files in `features/` are the recipes for the rest of the map. Run them in the same Chrome launch, against the same base URL, after this journey or from a fresh launch as their preconditions say.

If a step needs an OpenAI or Tavily key and neither the root `.env` nor the gear menu has one, stop and report that. Do not invent a key, do not request a real key, and do not treat the missing-key toast as a successful recipe.

## Evidence

Artifacts go in the `evidence_dir` from `instance.json`, which is `verification-runs/<stamp>/evidence/`. `verification-runs/` is gitignored. Cleanup does not delete it.

`drive-signup.sh` writes:

- `auth-screen.png` before submit
- `signup-response.json` with the `POST /api/auth/signup` status and body (`201`, `delivery` `log`)
- `signup-notice.png` showing the log-delivery notice
- `verification-log-line.txt`, the `INFO gsb.auth Verification link for ...` line from `logs/auth.log`
- `verification-token-sha256.txt`, sha256 of the token in that line
- `verified-chat.png` after the browser opens the logged link
- `me.json`, `GET /api/auth/me` (`200` and the email)
- `session-cookie-sha256.txt`, sha256 of the `gsb_session` cookie value
- `db-rows.txt` and `proof.txt`

The database proof reads `$RUN/data/auth.db` and requires:

- one `users` row for the email, `password_hash` starting with `$argon2id$`, `email_verified_at` set
- the password bytes absent from the sqlite file
- one `email_verification_tokens` row whose `token_hash` is the sha256 hex of the logged token, with `used_at` set
- the raw token absent from the sqlite file
- one `sessions` row whose `token_hash` is the sha256 of the cookie

That is the standard for this app: use the browser path, then check the row the click created. The logged link is the local delivery. Do not point `SMTP_HOST` at Resend or any other real mail server for a proof. A fake SMTP server belongs in `tests/test_smtp.py`; the browser journey uses the log line.

Screenshots, response bodies, the auth log, and `db-rows.txt` are all part of the proof. A screenshot of the chat without the users row is not enough. A passing unit test is not a substitute for this journey.

## Cleanup

```bash
bash .cursor/skills/verify-gsb-chef/scripts/cleanup.sh
```

This reads the process-group ids in `verification-runs/current/instance.json` and sends `SIGTERM`, then `SIGKILL` if needed, to those groups only. It never selects processes by name. It does not remove `verification-runs/<stamp>/`, the database, the logs, or the evidence. It does not remove the repo `data/` directory or `.langgraph_api`.

After a failed launch or a failed drive, run this before starting another attempt so the ports are free. Then confirm the evidence directory from the failed run is still on disk.

## Helpers

All four scripts live in `.cursor/skills/verify-gsb-chef/scripts/` and are executable.

```bash
bash .cursor/skills/verify-gsb-chef/scripts/launch.sh
bash .cursor/skills/verify-gsb-chef/scripts/doctor.sh
bash .cursor/skills/verify-gsb-chef/scripts/drive-signup.sh
bash .cursor/skills/verify-gsb-chef/scripts/cleanup.sh
python3 .cursor/skills/verify-gsb-chef/scripts/ports.py listeners 8000 2024 3000
```

`ports.py` is the read-only listener lookup used by launch and doctor. `drive-signup.sh` calls `drive-signup.mjs`. Do not invoke the `.mjs` file on its own; it expects `WEB_PACKAGE`, `VERIFY_BASE_URL`, `VERIFY_EMAIL`, `VERIFY_PASSWORD`, `VERIFY_AUTH_LOG`, and `VERIFY_EVIDENCE` from the shell wrapper.
