# gsb-chef verification map

This directory is the source for user-facing checks of gsb-chef. Read it before driving the app, then follow one feature file. The harness is Playwright against the browser UI in `web/`.

Launch, doctor, evidence, and cleanup are specified in `../SKILL.md`. Keep the map current with `/maintain-verification-skill` when the UI, routes, or auth flow change.

## Baseline preconditions

- One instance started by `bash .cursor/skills/verify-gsb-chef/scripts/launch.sh`.
- `bash .cursor/skills/verify-gsb-chef/scripts/doctor.sh` prints `DOCTOR OK`.
- The browser origin is `http://127.0.0.1:3000`.
- The auth database is the launch `GSB_AUTH_DB`, not `data/auth.db`, and its user, token, and session tables are empty before sign-up.
- `SMTP_HOST` is empty in the auth process, so the verification link is in `logs/auth.log`.
- Do not drive a server you did not start for this run. A second instance cannot bind 8000, 2024, or 3000, and it would share `.langgraph_api`.

## Driving conventions

- Open Chrome through Playwright as `../SKILL.md` describes. Wait for the label `Email` or, once signed in, the ingredient placeholder. Do not act on the `Loading…` screen.
- Prefer the accessible names in the feature files over CSS selectors.
- Capture the click and the resulting state. For sign-up that includes the auth log line and the SQLite rows.
- Leave evidence in the launch run's `evidence/` directory.
- If a precondition is missing, report the feature as not verified and name the missing piece. Do not change the journey so it passes.

## Features

- [Sign up and email verification](./signup-and-verification.md) creates an account, opens the logged link, and lands in the chat.
- [Login and session gate](./login-and-session.md) blocks unverified users and restores a verified session.
- [Login page and Google sign-in](./google-login.md) opens `/login`, hides Google until it is configured, and keeps `/api` behind the session.
- [Chat with the chef](./chef-chat.md) sends leftover ingredients and expects a GSB Konkani recipe. This needs real OpenAI and Tavily keys.
- [API keys in the gear menu](./provider-keys.md) stores OpenAI and Tavily keys in this browser.
- [Missing-key error](./missing-key-error.md) shows the error when a chat is sent with no key.
- [Thumbs feedback](./feedback.md) marks a finished chef reply up or down and records the request the UI sends.
