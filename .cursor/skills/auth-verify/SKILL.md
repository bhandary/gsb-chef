---
name: auth-verify
description: Check the email sign-up token lifecycle in auth.py. Use when changing signup, issue_verification_token, verify_email_token, hash_password, hash_token, or expiry, and when you need to know that a token verifies one account once, only before it expires, never after use, and that the database stores hashes rather than raw tokens or passwords.
---

# Auth verification

Confirm the sign-up promises in `auth.py`. Do not weaken a property, and do not change product code, to make a failing run pass. A failure is a counterexample. Report it in the words the assertion already uses (`verify_email_token`, `users.email_verified_at`, `email_verification_tokens.used_at`, `token_hash`, `password_hash`).

## Tool

Hypothesis `6.170.14`, pinned in the command below and in `requirements.txt`.

The lifecycle is an ordering question (issue, expire, consume, a second consume, a consume of someone else's row), which is the kind of question a TLA+ model can state. This repo is Python, and TLC would check a model, not `auth.py`. Deleting the `used_at` guard in `verify_email_token` would leave that model green. There is no model checker that runs this module. Hypothesis draws emails, passwords, offsets from `expires_at`, and sequences of `signup`, `issue_verification_token`, and `verify_email_token`, and the assertions call those functions. That is the cheapest check that fails when the real code breaks.

Argon2id comes from `argon2-cffi==25.1.0` (`PasswordHasher(type=Type.ID)` in `hash_password`). The property checks the stored string. It does not reimplement the hash.

## Promises

Every name below is a function in `auth.py` unless noted.

| Id | Promise | Code |
| --- | --- | --- |
| P1 | A successful `verify_email_token` returns the email of the user the token was issued to, and does not change `users.email_verified_at` for anyone else. | `issue_verification_token` stores `user_id`. `verify_email_token` updates `users` with `WHERE id = ?`. |
| P2 | The second `verify_email_token` of the same raw token raises `AuthError` code `used` and does not return another session. | The `used_at is not None` check, and `UPDATE ... WHERE id = ? AND used_at IS NULL AND expires_at > ?`. |
| P3 | `verify_email_token` succeeds only when `now` is strictly before the stored `expires_at`. At `expires_at` it raises `expired`. A call that raises does not change `users.email_verified_at` or `email_verification_tokens.used_at`. | The `expires_at <= current` check runs before either update. The same `UPDATE` also requires `expires_at > ?`. |
| P4 | `email_verification_tokens.token_hash` and `sessions.token_hash` are the sha256 hex digest from `hash_token`. They are not the raw token. The SQLite file does not contain the raw token. | `issue_verification_token` inserts `hash_token(token)`. `_create_session` inserts `hash_token(token)` for the session `verify_email_token` returns. |
| P5 | `users.password_hash` is an Argon2id PHC string (`$argon2id$...`), `verify_password` accepts it, and the column is not the password passed to `signup`. | `signup` inserts `hash_password(password)`. |

`verification/lifecycle.py` is the executable statement of those promises. `verification/probes.py` is one fixed scenario per promise. `verification/test_auth_lifecycle.py` is the Hypothesis search plus the broken variants.

Replacing an unused token (`issue_verification_token` deletes rows with `used_at IS NULL`) makes the previous raw token raise `invalid`. A used row is left in place and still raises `used`.

## Bounds and assumptions

- Emails drawn by Hypothesis match `[a-z0-9]{1,12}@[a-z0-9]{1,12}\.[a-z]{2,4}`. `normalize_email` accepts a wider set, including uppercase input, which `signup` lowercases.
- Passwords are 8 to 40 characters, code points 33 through 126. `signup` allows 8 to 200 characters and does not restrict the alphabet.
- Single-token search: 30 examples, plus the explicit cases `ttl_seconds=60` with `offset_seconds=0` and `offset_seconds=-1`. `offset_seconds` is added to the stored `expires_at`. TTL is 1 to 10000 seconds.
- Sequences: 20 examples, up to 8 steps, derandomized. Steps are `signup`, `issue_verification_token`, and `verify_email_token`. Shrinking is off for sequences because each shrink reruns Argon2id. The explicit cases above are the minimal counterexamples for P2 and P3.
- `now` is the argument `verify_email_token` already accepts. An `expired` rejection does not consume the token, so a later call with an earlier `now` can still succeed. Production callers pass `datetime.now()`.
- Two threads in one process may call `verify_email_token` on the same token. The check expects one success and one `used`. It assumes SQLite's default lock wait (5 seconds) and one database file. It does not cover more threads, other processes, or `timeout=0`.
- Password checks look at the `password_hash` column. They do not search the whole file for a short password, because an 8-character password can appear inside an Argon2 encoding by chance. Token checks do search the file bytes. Tokens are `secrets.token_urlsafe(32)`.

## Broken variants

`test_broken_variant_fails_its_property` copies `auth.py`, applies one edit, and runs the named probe in a subprocess whose working directory is that copy (so `import auth` is the variant). The probe must exit 1 and print `BROKEN:`. On unmodified `auth.py` the same probe prints `HOLDS`.

| Variant | Edit | Probe that must break |
| --- | --- | --- |
| `drop-used-guards` | Remove the `used_at is not None` check and `AND used_at IS NULL` from the `UPDATE`. Removing only the Python check still raises `used`, because the `UPDATE` remains. | `once` (P2) |
| `drop-expiry-guards` | Remove the `expires_at <= current` check and `AND expires_at > ?` from the `UPDATE`. | `expiry` (P3) |
| `verify-before-expiry-check` | `UPDATE users` and `commit` before the expiry check. | `rejected_is_noop` (P3) |
| `verify-every-account` | `UPDATE users` without `WHERE id = ?`. | `one_account` (P1) |
| `store-raw-token` | Insert the raw token instead of `hash_token(token)`. | `stored_token` (P4) |
| `store-raw-password` | Insert the password instead of `hash_password(password)`. | `password_hash` (P5) |

If a variant prints `HOLDS`, the property no longer sees that break. Fix the check. Do not delete the variant or loosen the assertion.

## Command

From the repository root, with the project virtualenv:

```bash
.venv/bin/python -m pip install 'hypothesis==6.170.14' && .venv/bin/python -m pytest verification/test_auth_lifecycle.py -q
```

`pytest.ini` also collects `verification/`, so a plain `pytest` run includes this file.

## Last confirmed

Last confirmed commit: `3096f353bddca63d0ddd2e650ae7813357e878d1`

The command was run on that tree after the scratch edit below was reverted: 16 passed. `auth.py` there still has both used-token guards, the expiry check before either update, `hash_token` on insert, and `hash_password` on signup. Re-run the command after you change `auth.py`, and replace this hash with the commit you just confirmed. Do not leave a hash here for a tree the command has not passed on.

## When the command fails

Stop. The Hypothesis output or the `BROKEN:` line is the counterexample. Do not edit `verification/` to accept the new behavior, and do not patch `auth.py` as part of following this skill.

A scratch deletion of both used-token guards (the `used_at is not None` check and `AND used_at IS NULL`) made the command fail. The explicit case was:

```text
test_token_verifies_one_account_once_before_expiry(
    email='cook@example.com',
    password='pantry-secret',
    ttl_seconds=60,
    offset_seconds=-1,
)
AssertionError: verify_email_token(now=2026-03-01T12:00:59+00:00) returned email 'cook@example.com' and a session token; expected AuthError 'used'
```

`test_two_threads_consume_a_token_once` reported `[('ok', 'cook@example.com'), ('ok', 'cook@example.com')]`. The `once` probe printed the same `BROKEN:` line for `now=2026-03-01T12:05:00+00:00`. Restoring `auth.py` made the command pass: 16 passed.

## What this does not cover

- `send_verification_email` when `SMTP_HOST` is set, and the text of the logged link, except that the raw token in that link is not what the database stores.
- `auth_app.py`, cookies, and the Next.js `/api/auth` routes.
- `login`, `logout`, and `current_user`, including session expiry. The session row created inside `verify_email_token` is checked only for P4.
- Provider API keys, the LangGraph server, and the chat UI.
- More than two concurrent `verify_email_token` callers, or SQLite opened with `timeout=0`.
- Passwords outside the alphabet and length above, and email addresses outside the pattern above.
