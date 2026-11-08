# GSB Chef

A Gaud Saraswat Brahmin Konkani chef. Tell it which ingredients you have left over and it searches for recipes.

The Python agent is served with the LangGraph dev server. The browser UI in `web/` is [Agent Chat UI](https://github.com/langchain-ai/agent-chat-ui) at commit `2624b821a4542e115a7e8eb8917e4cfb42397ce6` (MIT, Copyright (c) 2025 Brace Sproul; see `web/LICENSE`), with sign-up and API key settings added.

## Requirements

- Python 3.11 or newer
- Node.js 22
- pnpm 10.5.1 (declared in `web/package.json`)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

cd web
pnpm install
cp .env.example .env
cd ..
```

`.env` files are local. Do not commit them.

## Run

Start each process in its own terminal from the repository root, with the virtualenv active for the Python commands.

```bash
python -m auth_app
```

```bash
langgraph dev
```

```bash
cd web && pnpm dev
```

Open http://localhost:3000.

1. Create an account. With `SMTP_HOST` empty, the auth server prints a one-time verification link in its log. Open that link.
2. Open the gear icon and enter an OpenAI API key and a Tavily API key, or put those keys in the root `.env` and leave the fields blank.
3. Send a message listing leftover ingredients.

The graph id is `agent`. The UI expects the LangGraph server at http://localhost:2024.

## Accounts

Sign-up, verification, and sign-in are handled by the auth server on http://127.0.0.1:8000. The chat page calls it through the Next.js routes under `/api/auth`, which keep the session cookie on the UI origin.

- Passwords are hashed with Argon2id (`argon2-cffi`) and stored in SQLite at `data/auth.db` (override with `GSB_AUTH_DB`).
- Email verification uses a `secrets.token_urlsafe` token. Only its SHA-256 hash is stored. A token expires (24 hours by default, `GSB_VERIFICATION_TTL_SECONDS`) and cannot be used twice.
- After verification, the browser gets an httpOnly cookie named `gsb_session`. The server stores only the SHA-256 hash of that session token. Sessions last 14 days.
- Passwords are not logged. With SMTP unset, the auth log contains the verification link and the recipient address.

Leave `SMTP_HOST` empty to print the link locally. `python -m auth_app` reads those variables from `.env`. To send with Resend, set:

- `SMTP_HOST=smtp.resend.com`
- `SMTP_PORT=587`
- `SMTP_USERNAME=resend`
- `SMTP_PASSWORD` to the Resend API key
- `SMTP_FROM` to an address on a domain you have verified in Resend, for example `GSB Chef <no-reply@yourdomain.com>`
- `SMTP_TLS=true`, which is STARTTLS on port 587, not implicit SSL

The API key is not logged. Replace `yourdomain.com` before sending.

Signing up again with the same email and password before verification sends a new link. After verification, sign in at `/` or `/login`. Email and password sign-in is unchanged.

Google sign-in uses Authlib's OpenID Connect authorization-code flow with PKCE. The auth server checks `state`, `nonce`, and the ID token signature, issuer (`https://accounts.google.com`), audience, and expiry against Google's discovery document, and it requires `email_verified`. A verified Google email is created or linked to the password account with that email, then the same `gsb_session` cookie is set. Leave `GOOGLE_CLIENT_ID` empty to hide the button. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `APP_BASE_URL`. The redirect URI is `${APP_BASE_URL}/api/auth/google/callback` on the web origin, because the browser never calls the auth port directly. Do not set `GOOGLE_DISCOVERY_URL`; it exists so tests can serve a local discovery document.

In Google Cloud Console:

1. Create or select a project. Open APIs & Services → OAuth consent screen. Choose External (or Internal for a Workspace org). Set the app name to GSB Chef, add a support email, and add the scopes `openid`, `email`, and `profile` (the default ones are enough). If the app stays in Testing, add the Google accounts that may sign in as test users.
2. Open APIs & Services → Credentials → Create credentials → OAuth client ID → Web application.
3. Under Authorized redirect URIs, add these exactly, with no trailing slash:
   - `http://127.0.0.1:3000/api/auth/google/callback`
   - `http://localhost:3000/api/auth/google/callback`
   - `https://web-production-346c6.up.railway.app/api/auth/google/callback`
4. Copy the client ID into `GOOGLE_CLIENT_ID` and the client secret into `GOOGLE_CLIENT_SECRET`. Do not commit them.
5. Set `APP_BASE_URL` to the origin the browser uses: `http://127.0.0.1:3000` or `http://localhost:3000` locally, and `https://web-production-346c6.up.railway.app` on Railway. The auth server builds the redirect URI from that value.

The chat page requires a verified session. The Next.js `/api` proxy checks `gsb_session` with the auth server before it forwards anything to LangGraph, and it returns 401 `{"error":"Sign in required."}` when the cookie is missing or rejected. The LangGraph port itself still accepts requests that reach it directly; do not expose that port.

## API keys

OpenAI and Tavily keys typed into the gear menu are stored in this browser's localStorage:

- `gsb:chat:openaiApiKey`
- `gsb:chat:tavilyApiKey`
- `gsb:chat:providerKeyHost` (the LangGraph origin those keys belong to)

The UI sends them on each LangGraph request as `X-OpenAI-Api-Key` and `X-Tavily-Api-Key`. The agent process keeps them in memory for about 15 minutes, keyed by a random id, so a run can use them. They are not written into LangGraph run config. That config is saved under `.langgraph_api`, so putting the keys there would store them on disk. They are not written to `data/auth.db` and the agent does not log them.

If a field is blank, the agent uses `OPENAI_API_KEY` or `TAVILY_API_KEY` from the environment. Leave `LANGSMITH_TRACING` false unless you want traces to leave the machine.

## Tests

```bash
source .venv/bin/activate
pytest
```

The UI typecheck and production build:

```bash
cd web
pnpm exec tsc --noEmit
pnpm build
```
