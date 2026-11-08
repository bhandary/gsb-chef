# Login page and Google sign-in

`/login` is the account card in Sign in mode. Google is an extra way in, shown only when a client id is configured. The web `/api` proxy refuses LangGraph calls that do not have a session.

## Sub-features

- `login-page` shows the same card as sign-up, with Sign in already selected.
- `google-button-hidden` leaves the card without `Sign in with Google` when `GOOGLE_CLIENT_ID` is empty. That is how `launch.sh` starts.
- `google-authorize-redirect` sends the browser to `https://accounts.google.com/o/oauth2/v2/auth` with `client_id`, `redirect_uri`, `code_challenge`, `code_challenge_method=S256`, `state`, and `nonce` when a client id is set.
- `proxy-session-required` makes `GET /api/ok` on the web origin return 401 without a `gsb_session` cookie.

## How to get to it (user POV)

- Open `http://127.0.0.1:3000/login` while signed out.
- The heading is GSB Chef. Email and Password are on the card. Sign in is the selected mode and the submit button.
- With no Google client id, there is no Google button. Email and password sign-in still works from this page.
- With `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` set on the auth server, and `APP_BASE_URL` set to `http://127.0.0.1:3000`, choose Sign in with Google. The browser leaves for accounts.google.com. A real Google account cannot finish from a fake client id.
- Ask for a recipe only after a session exists. The page at `/api/...` otherwise says to sign in.

## Driving it with Playwright

Preconditions:

- `DOCTOR OK` on the launch instance. Doctor also checks that `GET http://127.0.0.1:3000/api/ok` is 401 `{"error":"Sign in required."}`.
- Use a fresh Playwright browser context.
- Launch Chrome with `channel: "chrome"` and args `--no-sandbox` and `--disable-dev-shm-usage`, from `@playwright/test` resolved via `createRequire(<repo>/web/package.json)`.
- The default launch clears `GOOGLE_CLIENT_ID`. Do not export a client id for the signup proof.

- **Login page.** Go to `http://127.0.0.1:3000/login`. Wait for the label `Email`. The heading `GSB Chef` is visible. The submit button is `Sign in`. The ingredient placeholder is absent.
- **Google hidden.** The link `Sign in with Google` is absent. `GET /api/auth/google` returns `{"enabled":false}`.
- **Proxy closed.** `GET http://127.0.0.1:3000/api/ok` with no cookie returns 401 and `{"error":"Sign in required."}`. `GET http://127.0.0.1:2024/ok` still returns 200. The agent process is not the session gate.
- **Authorize redirect.** This step is a separate auth and web process, not the cleared launch. Set `GOOGLE_CLIENT_ID` to a non-secret fake id such as `test-client-id.apps.googleusercontent.com`, set `GOOGLE_CLIENT_SECRET` to any non-empty fake value, and set `APP_BASE_URL=http://127.0.0.1:3000`. Open `/login`, wait until the link `Sign in with Google` is visible, and click it. Capture the first request whose URL contains `accounts.google.com`. It must include `client_id` equal to the fake id, `redirect_uri` equal to `http://127.0.0.1:3000/api/auth/google/callback`, `code_challenge`, `code_challenge_method=S256`, `state`, and `nonce`. Stop there. Google will reject the fake client. Do not type a real Google password.

## Gotchas

- Two controls are named `Sign in` on `/login`: the mode button and the submit button. `Sign in with Google` is a link, present only after `/api/auth/google` says `enabled: true`.
- `launch.sh` sets `GOOGLE_CLIENT_ID` empty so a developer `.env` cannot turn the button on during the signup proof.
- The redirect URI is on the web origin, not port 8000. `APP_BASE_URL` must be the origin the browser is using, without a path or a trailing slash.
- A real Google login needs an OAuth client whose authorized redirect URIs include that callback. This skill does not complete one.
- `gsb_session` is httpOnly. The proxy reads it from the cookie header and asks the auth server `/auth/me`. Do not send the cookie value to LangGraph yourself, and do not log it.
- The authorization code arrives on the callback query string. The Next route posts it to the auth server and must not print it.
