import hashlib
import logging
import os
import secrets
import smtplib
import sqlite3
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from argon2.low_level import Type

logger = logging.getLogger("gsb.auth")

_HASHER = PasswordHasher(type=Type.ID)
_DUMMY_PASSWORD_HASH: str | None = None
_SESSION_TTL = timedelta(days=14)
_DEFAULT_VERIFICATION_TTL = timedelta(hours=24)


class AuthError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _HASHER.verify(password_hash, password)
    except VerificationError:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def db_path() -> Path:
    return Path(os.environ.get("GSB_AUTH_DB", "data/auth.db"))


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            email_verified_at TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )


def _now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def verification_ttl() -> timedelta:
    raw = os.getenv("GSB_VERIFICATION_TTL_SECONDS")
    if raw is None or raw.strip() == "":
        return _DEFAULT_VERIFICATION_TTL
    return timedelta(seconds=int(raw))


def normalize_email(email: str) -> str:
    cleaned = email.strip().lower()
    if len(cleaned) > 254 or cleaned.count("@") != 1 or any(ch.isspace() for ch in cleaned):
        raise AuthError("invalid_email", "Enter a valid email address.")
    local, domain = cleaned.split("@")
    if not local or "." not in domain:
        raise AuthError("invalid_email", "Enter a valid email address.")
    return cleaned


def _check_password_length(password: str) -> None:
    if len(password) < 8 or len(password) > 200:
        raise AuthError("invalid_password", "Password must be 8 to 200 characters.")


def _dummy_hash() -> str:
    global _DUMMY_PASSWORD_HASH
    if _DUMMY_PASSWORD_HASH is None:
        _DUMMY_PASSWORD_HASH = hash_password("not-a-user-password")
    return _DUMMY_PASSWORD_HASH


def issue_verification_token(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    now: datetime | None = None,
    ttl: timedelta | None = None,
) -> str:
    current = _now(now)
    expires_at = current + (ttl if ttl is not None else verification_ttl())
    token = secrets.token_urlsafe(32)
    conn.execute(
        "DELETE FROM email_verification_tokens WHERE user_id = ? AND used_at IS NULL",
        (user_id,),
    )
    conn.execute(
        """
        INSERT INTO email_verification_tokens
            (user_id, token_hash, expires_at, used_at, created_at)
        VALUES (?, ?, ?, NULL, ?)
        """,
        (user_id, hash_token(token), _iso(expires_at), _iso(current)),
    )
    conn.commit()
    return token


def _app_base_url() -> str:
    return os.getenv("APP_BASE_URL", "http://localhost:3000").rstrip("/")


def verification_link(token: str) -> str:
    return f"{_app_base_url()}/verify#token={token}"


def send_verification_email(to: str, link: str) -> str:
    host = os.getenv("SMTP_HOST", "").strip()
    if not host:
        logger.info("Verification link for %s: %s", to, link)
        return "log"

    message = EmailMessage()
    message["Subject"] = "Verify your GSB Chef email"
    message["From"] = os.getenv("SMTP_FROM", "gsb-chef@localhost")
    message["To"] = to
    message.set_content(
        "Verify your email by opening this link:\n\n"
        f"{link}\n\n"
        "The link can only be used once."
    )
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        if os.getenv("SMTP_TLS", "true").lower() != "false":
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)
    return "smtp"


def _deliver_verification(conn: sqlite3.Connection, user_id: int, email: str) -> str:
    token = issue_verification_token(conn, user_id)
    return send_verification_email(email, verification_link(token))


def signup(email: str, password: str) -> dict[str, str | bool]:
    cleaned = normalize_email(email)
    _check_password_length(password)
    conn = connect()
    try:
        existing = conn.execute(
            "SELECT id, password_hash, email_verified_at FROM users WHERE email = ?",
            (cleaned,),
        ).fetchone()
        if existing is not None:
            if existing["email_verified_at"]:
                raise AuthError(
                    "exists",
                    "An account with that email already exists.",
                    409,
                )
            if not verify_password(existing["password_hash"], password):
                raise AuthError("invalid", "Invalid email or password.", 401)
            delivery = _deliver_verification(conn, existing["id"], cleaned)
            return {"ok": True, "delivery": delivery}

        now = _iso(_now())
        cursor = conn.execute(
            """
            INSERT INTO users (email, password_hash, email_verified_at, created_at)
            VALUES (?, ?, NULL, ?)
            """,
            (cleaned, hash_password(password), now),
        )
        conn.commit()
        delivery = _deliver_verification(conn, int(cursor.lastrowid), cleaned)
        return {"ok": True, "delivery": delivery}
    finally:
        conn.close()


def verify_email_token(token: str, *, now: datetime | None = None) -> dict:
    current = _now(now)
    token_hash = hash_token(token)
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT id, user_id, expires_at, used_at
            FROM email_verification_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if row is None:
            raise AuthError("invalid", "This verification link is invalid.")
        if row["used_at"] is not None:
            raise AuthError("used", "This verification link has already been used.")
        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at <= current:
            raise AuthError("expired", "This verification link has expired.")

        updated = conn.execute(
            """
            UPDATE email_verification_tokens
            SET used_at = ?
            WHERE id = ? AND used_at IS NULL AND expires_at > ?
            """,
            (_iso(current), row["id"], _iso(current)),
        )
        if updated.rowcount != 1:
            conn.rollback()
            raise AuthError("used", "This verification link has already been used.")
        conn.execute(
            "UPDATE users SET email_verified_at = ? WHERE id = ?",
            (_iso(current), row["user_id"]),
        )
        conn.commit()
        user = conn.execute(
            "SELECT id, email FROM users WHERE id = ?",
            (row["user_id"],),
        ).fetchone()
        session_token = _create_session(conn, user["id"], now=current)
        return {"email": user["email"], "token": session_token}
    finally:
        conn.close()


def _create_session(
    conn: sqlite3.Connection, user_id: int, *, now: datetime | None = None
) -> str:
    current = _now(now)
    token = secrets.token_urlsafe(32)
    conn.execute(
        """
        INSERT INTO sessions (user_id, token_hash, expires_at, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            hash_token(token),
            _iso(current + _SESSION_TTL),
            _iso(current),
        ),
    )
    conn.commit()
    return token


def login(email: str, password: str) -> dict[str, str]:
    cleaned = normalize_email(email)
    conn = connect()
    try:
        user = conn.execute(
            "SELECT id, email, password_hash, email_verified_at FROM users WHERE email = ?",
            (cleaned,),
        ).fetchone()
        password_hash = user["password_hash"] if user is not None else _dummy_hash()
        if not verify_password(password_hash, password) or user is None:
            raise AuthError("invalid", "Invalid email or password.", 401)
        if not user["email_verified_at"]:
            raise AuthError(
                "unverified",
                "Verify your email before signing in.",
                403,
            )
        token = _create_session(conn, user["id"])
        return {"email": user["email"], "token": token}
    finally:
        conn.close()


def logout(token: str) -> None:
    if not token:
        return
    conn = connect()
    try:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
        conn.commit()
    finally:
        conn.close()


def current_user(token: str, *, now: datetime | None = None) -> dict[str, str]:
    if not token:
        raise AuthError("unauthorized", "Sign in required.", 401)
    current = _now(now)
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT sessions.expires_at, users.email, users.email_verified_at
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ?
            """,
            (hash_token(token),),
        ).fetchone()
        if row is None or not row["email_verified_at"]:
            raise AuthError("unauthorized", "Sign in required.", 401)
        if datetime.fromisoformat(row["expires_at"]) <= current:
            raise AuthError("unauthorized", "Sign in required.", 401)
        return {"email": row["email"]}
    finally:
        conn.close()
