# Sign up and email verification

A new user creates an account, reads the verification link from the auth server log, opens it, and arrives at the recipe chat with a verified session.

## Sub-features

- `signup-form` shows Email, Password, and Create account on `/`.
- `signup-log` accepts a new email and tells the user to open the link printed in the auth server log.
- `verify-link` opens `/verify#token=` once and replaces the page with the chat.
- `verified-session` makes `GET /api/auth/me` return that email.

## How to get to it (user POV)

- Open `http://127.0.0.1:3000/`. The page heading is GSB Chef.
- Leave the Sign up mode selected. It is the default.
- After Create account, copy the verification link from the auth server log and open it in the same browser.

## Driving it with Playwright

Preconditions:

- `bash .cursor/skills/verify-gsb-chef/scripts/doctor.sh` prints `DOCTOR OK`.
- The launch database has no rows in `users`, `email_verification_tokens`, or `sessions`. The file itself may already exist.
- The auth log is the path `auth_log` in `verification-runs/current/instance.json`.

- **Run the journey.** From the repo root, run `bash .cursor/skills/verify-gsb-chef/scripts/drive-signup.sh`.
- **Open the form.** The script waits for the label `Email` and the button `Create account`, then writes `evidence/auth-screen.png`.
- **Create the account.** It fills `gsb-verify@example.com` and `verify-skill-pass`, clicks `Create account`, and records `POST /api/auth/signup`. The status is 201 and the body has `"delivery": "log"`. The page shows `Account created. Open the verification link printed in the auth server log.`
- **Open the logged link.** It reads `Verification link for gsb-verify@example.com: http://127.0.0.1:3000/verify#token=` from the auth log and navigates to that URL.
- **Land in the chat.** The placeholder `List leftover ingredients, for example rice, coconut, and curry leaves` and the button `API key settings` are visible. `evidence/verified-chat.png` shows that screen.
- **Confirm the session.** `GET /api/auth/me` returns 200 and `{"email":"gsb-verify@example.com"}`. The cookie jar has `gsb_session`.
- **Confirm the database.** `evidence/db-rows.txt` shows the `users` row with an `$argon2id$` password hash and `email_verified_at` set, the verification `token_hash` equal to the sha256 of the logged token with `used_at` set, and `sessions.token_hash` equal to the sha256 of `gsb_session`. The sqlite file does not contain the password or the raw token. `evidence/proof.txt` says `signup-and-verification PASS`.

## Gotchas

- `curl -f` against `/auth/me` fails on the expected 401. The ready check is the status and the body `Sign in required.`
- Opening `http://127.0.0.1:3000/` before it hydrates shows `Loading…`. Wait for the Email label. The dev server must be the one started with `allowedDevOrigins` including `127.0.0.1`.
- The mode button `Sign up` is not the submit button. The submit button is `Create account`.
- The verification page reads the hash once and then replaces the URL with `/verify`. Reloading that address shows `This verification link is invalid.`
- A second click of the same link shows `This verification link has already been used.`
- Sign-up does not set `gsb_session`. The cookie appears when the verify request succeeds.
- If `SMTP_HOST` is set, the notice is the email sentence and the log line is absent. This journey is specified for log delivery only. Do not send through Resend to make it pass.
- Reusing `gsb-verify@example.com` after it is verified returns `An account with that email already exists.` Launch a new empty database for another run.
