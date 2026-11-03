# Login and session gate

The chat stays behind a verified account. An unverified user cannot sign in. A verified user can sign out and sign in again. The session cookie is what the next page load trusts.

## Sub-features

- `gate-signed-out` shows the account form, not the composer, when `/api/auth/me` is 401.
- `login-unverified` rejects a password before the email link is opened.
- `login-verified` accepts the same password after verification and shows the composer.
- `logout` returns to the account form and `/api/auth/me` is 401 again.

## How to get to it (user POV)

- Open `http://127.0.0.1:3000/` while signed out.
- Choose Sign in, enter the email and password, and submit Sign in.
- After a verified session, choose Sign out in the chat header.

## Driving it with Playwright

Preconditions:

- `DOCTOR OK` on the launch instance.
- Use a fresh Playwright browser context so it does not inherit another session.
- The unverified check needs an account that has been created and not yet verified. The verified check needs the account from `signup-and-verification.md`.
- Launch Chrome with `channel: "chrome"` and args `--no-sandbox` and `--disable-dev-shm-usage`, from `@playwright/test` resolved via `createRequire(<repo>/web/package.json)`.

- **Signed-out gate.** Go to `http://127.0.0.1:3000/`. Wait for the label `Email`. The ingredient placeholder is absent. `GET /api/auth/me` returns 401 and `{"error":"Sign in required."}`.
- **Unverified sign-in.** Create a second account, `gsb-unverified@example.com` / `verify-skill-pass`, with Create account, and do not open its log link. Click the button `Sign in` to switch mode, fill that email and password, and click the submit button named `Sign in`. The page shows `Verify your email before signing in.` The composer is still absent.
- **Verified sign-in.** Complete `signup-and-verification.md` for `gsb-verify@example.com`. Click `Sign out`. Wait until the label `Email` is back. Switch to Sign in, fill `gsb-verify@example.com` and `verify-skill-pass`, and submit `Sign in`. The ingredient placeholder returns.
- **Session survives reload.** Reload `http://127.0.0.1:3000/`. The placeholder is visible without submitting the form again. `GET /api/auth/me` returns 200 and the email.
- **Sign out.** Click `Sign out`. The Email label returns and `GET /api/auth/me` returns 401.

## Gotchas

- Two controls are named `Sign in`: the mode button and, after the mode switches, the submit button. Click the mode button first. The submit button reads `Create account` while Sign up is selected.
- `gsb_session` is httpOnly. A check of `document.cookie` misses a valid session. Use the Playwright cookie jar or `/api/auth/me`.
- Signing in before verification does not consume the verification token. The log link still works afterward.
- Wrong password text is `Invalid email or password.` Do not treat that as the unverified-email result.
