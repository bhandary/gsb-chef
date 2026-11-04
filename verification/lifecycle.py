"""Checks for the sign-up token lifecycle implemented in auth.py.

Each check calls the real functions. A failing AssertionError names the
function, the column, and the call that broke the promise.
"""

from __future__ import annotations

import io
import logging
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import auth

_HEX_SHA256 = re.compile(r"[0-9a-f]{64}")
ISSUED_AT = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


@contextmanager
def fresh_database():
    previous = os.environ.get("GSB_AUTH_DB")
    previous_smtp = os.environ.get("SMTP_HOST")
    previous_ttl = os.environ.get("GSB_VERIFICATION_TTL_SECONDS")
    previous_base = os.environ.get("APP_BASE_URL")
    with tempfile.TemporaryDirectory() as directory:
        os.environ["GSB_AUTH_DB"] = str(Path(directory) / "auth.db")
        os.environ["SMTP_HOST"] = ""
        os.environ["APP_BASE_URL"] = "http://localhost:3000"
        os.environ.pop("GSB_VERIFICATION_TTL_SECONDS", None)
        try:
            yield Path(os.environ["GSB_AUTH_DB"])
        finally:
            if previous is None:
                os.environ.pop("GSB_AUTH_DB", None)
            else:
                os.environ["GSB_AUTH_DB"] = previous
            if previous_smtp is None:
                os.environ.pop("SMTP_HOST", None)
            else:
                os.environ["SMTP_HOST"] = previous_smtp
            if previous_ttl is None:
                os.environ.pop("GSB_VERIFICATION_TTL_SECONDS", None)
            else:
                os.environ["GSB_VERIFICATION_TTL_SECONDS"] = previous_ttl
            if previous_base is None:
                os.environ.pop("APP_BASE_URL", None)
            else:
                os.environ["APP_BASE_URL"] = previous_base


def capture_signup(email: str, password: str) -> str:
    """Call auth.signup and return the raw token it logged."""
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    logger = logging.getLogger("gsb.auth")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        auth.signup(email, password)
    finally:
        logger.removeHandler(handler)
    text = buffer.getvalue()
    marker = "#token="
    if marker not in text:
        raise AssertionError("auth.signup did not log a verification token")
    return text.rsplit(marker, 1)[1].split()[0].strip()


def user_id(conn, email: str) -> int:
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if row is None:
        raise AssertionError(f"users row for {email!r} is missing after signup")
    return int(row["id"])


def stored_expiry(conn, raw_token: str) -> datetime:
    row = conn.execute(
        """
        SELECT expires_at FROM email_verification_tokens WHERE token_hash = ?
        """,
        (auth.hash_token(raw_token),),
    ).fetchone()
    if row is None:
        raise AssertionError(
            "issue_verification_token did not store hash_token(token) in "
            "email_verification_tokens.token_hash"
        )
    return datetime.fromisoformat(row["expires_at"])


def verified_at(conn) -> dict[str, str | None]:
    return {
        row["email"]: row["email_verified_at"]
        for row in conn.execute("SELECT email, email_verified_at FROM users")
    }


def used_at(conn) -> dict[str, str | None]:
    return {
        row["token_hash"]: row["used_at"]
        for row in conn.execute(
            "SELECT token_hash, used_at FROM email_verification_tokens"
        )
    }


def assert_storage(conn, passwords: dict[str, str], raw_secrets: set[str]) -> None:
    """P4 and P5: stored secrets are hashes, never the raw values."""
    for row in conn.execute("SELECT email, password_hash FROM users"):
        stored = row["password_hash"]
        password = passwords[row["email"]]
        if not isinstance(stored, str) or not stored.startswith("$argon2id$"):
            raise AssertionError(
                "users.password_hash for "
                f"{row['email']} is not an Argon2id PHC string "
                f"(auth.hash_password / PasswordHasher type Type.ID): {stored!r}"
            )
        if stored == password or (password and password in stored):
            raise AssertionError(
                f"users.password_hash for {row['email']} contains the password "
                "passed to auth.signup"
            )
        if not auth.verify_password(stored, password):
            raise AssertionError(
                f"auth.verify_password rejected users.password_hash for {row['email']}"
            )

    for row in conn.execute(
        """
        SELECT token_hash, expires_at, used_at, created_at
        FROM email_verification_tokens
        """
    ):
        _reject_raw_column("email_verification_tokens", row, raw_secrets)

    for row in conn.execute(
        "SELECT token_hash, expires_at, created_at FROM sessions"
    ):
        _reject_raw_column("sessions", row, raw_secrets)

    blob = Path(auth.db_path()).read_bytes()
    for raw in raw_secrets:
        if raw.encode("utf-8") in blob:
            raise AssertionError(
                "GSB_AUTH_DB file contains a raw verification or session token "
                "returned by issue_verification_token, signup, or verify_email_token"
            )


def _reject_raw_column(table: str, row, raw_secrets: set[str]) -> None:
    stored = row["token_hash"]
    if not isinstance(stored, str) or _HEX_SHA256.fullmatch(stored) is None:
        raise AssertionError(
            f"{table}.token_hash is not the sha256 hex digest from auth.hash_token: "
            f"{stored!r}"
        )
    if stored in raw_secrets:
        raise AssertionError(f"{table}.token_hash equals a raw token")
    for raw in raw_secrets:
        for column in row.keys():
            value = row[column]
            if isinstance(value, str) and raw in value:
                raise AssertionError(
                    f"{table}.{column} contains a raw token from "
                    "issue_verification_token or _create_session"
                )


def expect_verify(
    raw_token: str,
    when: datetime,
    outcome: str,
    *,
    email: str | None,
    passwords: dict[str, str],
    raw_secrets: set[str],
) -> str | None:
    """Run auth.verify_email_token and require one observable outcome.

    outcome is ok, used, expired, or invalid. A rejection must leave
    users.email_verified_at and email_verification_tokens.used_at unchanged.
    A success must verify only `email` and consume that token.
    """
    conn = auth.connect()
    try:
        before_users = verified_at(conn)
        before_used = used_at(conn)
    finally:
        conn.close()

    try:
        result = auth.verify_email_token(raw_token, now=when)
    except auth.AuthError as exc:
        if outcome == "ok":
            raise AssertionError(
                "verify_email_token"
                f"(now={when.isoformat()}) raised AuthError {exc.code!r} "
                f"for the token issued to {email!r}; expected success"
            ) from exc
        if exc.code != outcome:
            raise AssertionError(
                "verify_email_token"
                f"(now={when.isoformat()}) raised AuthError {exc.code!r}, "
                f"expected {outcome!r}"
            ) from exc
        conn = auth.connect()
        try:
            after_users = verified_at(conn)
            after_used = used_at(conn)
            if after_users != before_users:
                raise AssertionError(
                    f"verify_email_token raised {exc.code!r} but changed "
                    f"users.email_verified_at from {before_users} to {after_users}"
                )
            if after_used != before_used:
                raise AssertionError(
                    f"verify_email_token raised {exc.code!r} but changed "
                    "email_verification_tokens.used_at"
                )
            assert_storage(conn, passwords, raw_secrets)
        finally:
            conn.close()
        return None

    if outcome != "ok":
        raise AssertionError(
            "verify_email_token"
            f"(now={when.isoformat()}) returned email {result.get('email')!r} "
            f"and a session token; expected AuthError {outcome!r}"
        )
    if result.get("email") != email:
        raise AssertionError(
            "verify_email_token returned "
            f"{result.get('email')!r} for a token issued to {email!r}"
        )
    session = result.get("token")
    if not isinstance(session, str) or not session:
        raise AssertionError("verify_email_token did not return a session token")
    raw_secrets.add(session)

    conn = auth.connect()
    try:
        after_users = verified_at(conn)
        after_used = used_at(conn)
        for address, stamp in after_users.items():
            if address == email:
                if not stamp:
                    raise AssertionError(
                        "verify_email_token succeeded but users.email_verified_at "
                        f"for {email!r} is NULL"
                    )
                continue
            if stamp != before_users.get(address):
                raise AssertionError(
                    "verify_email_token for "
                    f"{email!r} changed users.email_verified_at for {address!r} "
                    f"from {before_users.get(address)!r} to {stamp!r}"
                )
        token_hash = auth.hash_token(raw_token)
        if after_used.get(token_hash) is None:
            raise AssertionError(
                "verify_email_token succeeded but "
                "email_verification_tokens.used_at is still NULL for hash_token(token)"
            )
        assert_storage(conn, passwords, raw_secrets)
    finally:
        conn.close()
    return session


def add_user(email: str, password: str, *, now: datetime | None = None) -> None:
    """Insert one unverified user the same way signup stores a password."""
    moment = (now or ISSUED_AT).isoformat()
    conn = auth.connect()
    try:
        conn.execute(
            """
            INSERT INTO users (email, password_hash, email_verified_at, created_at)
            VALUES (?, ?, NULL, ?)
            """,
            (email, auth.hash_password(password), moment),
        )
        conn.commit()
    finally:
        conn.close()
