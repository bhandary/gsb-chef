"""Fixed scenarios that must hold on auth.py and fail on a broken variant.

Run one check: python -m verification.probes <name>
Exit 0 prints HOLDS. Exit 1 prints BROKEN and the assertion.
"""

from __future__ import annotations

import sys
from datetime import timedelta

import auth
from verification.lifecycle import (
    ISSUED_AT,
    add_user,
    assert_storage,
    capture_signup,
    expect_verify,
    fresh_database,
    stored_expiry,
    user_id,
    verified_at,
)

BYSTANDER = "bystander@example.com"
BYSTANDER_PASSWORD = "bystander-pass"


def _passwords(email: str, password: str) -> dict[str, str]:
    return {email: password, BYSTANDER: BYSTANDER_PASSWORD}


def check_once() -> None:
    """P2. The second verify_email_token for one raw token raises used."""
    email = "cook@example.com"
    password = "pantry-secret"
    with fresh_database():
        add_user(BYSTANDER, BYSTANDER_PASSWORD)
        add_user(email, password)
        conn = auth.connect()
        try:
            raw = auth.issue_verification_token(
                conn, user_id(conn, email), now=ISSUED_AT, ttl=timedelta(hours=1)
            )
        finally:
            conn.close()
        secrets = {raw}
        when = ISSUED_AT + timedelta(minutes=5)
        passwords = _passwords(email, password)
        expect_verify(
            raw, when, "ok", email=email, passwords=passwords, raw_secrets=secrets
        )
        expect_verify(
            raw, when, "used", email=email, passwords=passwords, raw_secrets=secrets
        )


def check_expiry() -> None:
    """P3. verify_email_token at expires_at raises expired and writes nothing."""
    email = "cook@example.com"
    password = "pantry-secret"
    with fresh_database():
        add_user(email, password)
        conn = auth.connect()
        try:
            raw = auth.issue_verification_token(
                conn, user_id(conn, email), now=ISSUED_AT, ttl=timedelta(seconds=60)
            )
            expires_at = stored_expiry(conn, raw)
        finally:
            conn.close()
        expect_verify(
            raw,
            expires_at,
            "expired",
            email=email,
            passwords={email: password},
            raw_secrets={raw},
        )


def check_rejected_is_noop() -> None:
    """P3 reorder. An expired call must not set users.email_verified_at."""
    check_expiry()
    email = "cook@example.com"
    with fresh_database():
        add_user(email, "pantry-secret")
        conn = auth.connect()
        try:
            raw = auth.issue_verification_token(
                conn, user_id(conn, email), now=ISSUED_AT, ttl=timedelta(seconds=60)
            )
            expires_at = stored_expiry(conn, raw)
        finally:
            conn.close()
        try:
            auth.verify_email_token(raw, now=expires_at)
        except auth.AuthError as exc:
            if exc.code != "expired":
                raise AssertionError(
                    f"verify_email_token at expires_at raised {exc.code!r}, "
                    "expected 'expired'"
                ) from exc
        else:
            raise AssertionError(
                "verify_email_token at expires_at returned success"
            )
        conn = auth.connect()
        try:
            stamp = verified_at(conn)[email]
        finally:
            conn.close()
        if stamp is not None:
            raise AssertionError(
                "verify_email_token raised expired after writing "
                f"users.email_verified_at={stamp!r} for {email!r}"
            )


def check_one_account() -> None:
    """P1. One token sets email_verified_at only on the user it was issued to."""
    email = "cook@example.com"
    password = "pantry-secret"
    with fresh_database():
        add_user(BYSTANDER, BYSTANDER_PASSWORD)
        add_user(email, password)
        conn = auth.connect()
        try:
            raw = auth.issue_verification_token(
                conn, user_id(conn, email), now=ISSUED_AT, ttl=timedelta(hours=1)
            )
        finally:
            conn.close()
        expect_verify(
            raw,
            ISSUED_AT,
            "ok",
            email=email,
            passwords=_passwords(email, password),
            raw_secrets={raw},
        )


def check_stored_token() -> None:
    """P4. email_verification_tokens.token_hash is hash_token(token), not token."""
    email = "cook@example.com"
    password = "pantry-secret"
    with fresh_database():
        add_user(email, password)
        conn = auth.connect()
        try:
            raw = auth.issue_verification_token(
                conn, user_id(conn, email), now=ISSUED_AT, ttl=timedelta(hours=1)
            )
            assert_storage(conn, {email: password}, {raw})
            row = conn.execute(
                "SELECT token_hash FROM email_verification_tokens"
            ).fetchone()
            if row["token_hash"] != auth.hash_token(raw):
                raise AssertionError(
                    "email_verification_tokens.token_hash does not equal "
                    "auth.hash_token(token) returned by issue_verification_token"
                )
        finally:
            conn.close()


def check_password_hash() -> None:
    """P5. auth.signup stores an Argon2id hash, not the password."""
    email = "cook@example.com"
    password = "pantry-secret"
    with fresh_database():
        capture_signup(email, password)
        conn = auth.connect()
        try:
            assert_storage(conn, {email: password}, set())
        finally:
            conn.close()


CHECKS = {
    "once": check_once,
    "expiry": check_expiry,
    "rejected_is_noop": check_rejected_is_noop,
    "one_account": check_one_account,
    "stored_token": check_stored_token,
    "password_hash": check_password_hash,
}


def main() -> None:
    name = sys.argv[1]
    try:
        CHECKS[name]()
    except AssertionError as exc:
        print(f"BROKEN: {exc}")
        raise SystemExit(1) from None
    print("HOLDS")


if __name__ == "__main__":
    main()
