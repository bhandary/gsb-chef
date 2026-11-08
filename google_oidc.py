"""Google OpenID Connect sign-in.

Authlib runs the authorization-code flow with PKCE, then checks the ID token
against the provider discovery document. State, nonce, and the PKCE verifier
stay in SQLite so the browser can return to the web origin while the auth
server exchanges the code. Tokens and the client secret are never logged.

GOOGLE_DISCOVERY_URL overrides the discovery document for tests. Leave it
unset so production uses Google's document.
"""

from __future__ import annotations

import logging
import os
import time

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.responses import Response

import auth

logger = logging.getLogger("gsb.auth")

GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_DISCOVERY_URL = (
    "https://accounts.google.com/.well-known/openid-configuration"
)
_STATE_TTL_SECONDS = 600


_SECRET_MARKERS = (
    "code_verifier",
    "id_token",
    "client_secret",
    "access_token",
    "refresh_token",
)
_LOGGER_HANDLE = logging.Logger.handle
_HANDLE_INSTALLED = False


def _drop_secret_records(self, record):
    try:
        if record.name.startswith(("authlib", "httpx", "httpcore")):
            message = record.getMessage().lower()
            if any(marker in message for marker in _SECRET_MARKERS):
                return
    except Exception:
        pass
    return _LOGGER_HANDLE(self, record)


def _silence_token_logs() -> None:
    global _HANDLE_INSTALLED
    for name in ("authlib", "httpx", "httpcore", "python_multipart"):
        logging.getLogger(name).setLevel(logging.INFO)
    if not _HANDLE_INSTALLED:
        logging.Logger.handle = _drop_secret_records
        _HANDLE_INSTALLED = True


_silence_token_logs()


class SqliteOAuthCache:
    """Authlib state cache. Values are single-use and expire after 10 minutes."""

    async def get(self, key: str):
        conn = auth.connect()
        try:
            _ensure_cache(conn)
            row = conn.execute(
                "SELECT cache_value, expires_at FROM oauth_transactions WHERE cache_key = ?",
                (str(key),),
            ).fetchone()
            conn.execute(
                "DELETE FROM oauth_transactions WHERE cache_key = ? OR expires_at <= ?",
                (str(key), time.time()),
            )
            conn.commit()
            if row is None or row["expires_at"] <= time.time():
                return None
            return row["cache_value"]
        finally:
            conn.close()

    async def set(self, key: str, value: str, expires_in: int = _STATE_TTL_SECONDS):
        ttl = min(int(expires_in or _STATE_TTL_SECONDS), _STATE_TTL_SECONDS)
        conn = auth.connect()
        try:
            _ensure_cache(conn)
            conn.execute(
                """
                INSERT INTO oauth_transactions (cache_key, cache_value, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    cache_value = excluded.cache_value,
                    expires_at = excluded.expires_at
                """,
                (str(key), value, time.time() + ttl),
            )
            conn.commit()
        finally:
            conn.close()

    async def delete(self, key: str):
        conn = auth.connect()
        try:
            _ensure_cache(conn)
            conn.execute(
                "DELETE FROM oauth_transactions WHERE cache_key = ?",
                (str(key),),
            )
            conn.commit()
        finally:
            conn.close()


def _ensure_cache(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS oauth_transactions (
            cache_key TEXT PRIMARY KEY,
            cache_value TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )


def google_client_id() -> str:
    return os.getenv("GOOGLE_CLIENT_ID", "").strip()


def google_client_secret() -> str:
    return os.getenv("GOOGLE_CLIENT_SECRET", "").strip()


def google_enabled() -> bool:
    return bool(google_client_id())


def redirect_uri() -> str:
    return f"{auth._app_base_url()}/api/auth/google/callback"


def discovery_url() -> str:
    configured = os.getenv("GOOGLE_DISCOVERY_URL", "").strip()
    return configured or GOOGLE_DISCOVERY_URL


def _client():
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth(cache=SqliteOAuthCache())
    return oauth.register(
        name="google",
        client_id=google_client_id(),
        client_secret=google_client_secret(),
        server_metadata_url=discovery_url(),
        client_kwargs={
            "scope": "openid email profile",
            "code_challenge_method": "S256",
        },
    )


def _configured_response() -> JSONResponse | None:
    if google_client_id() and google_client_secret():
        return None
    return JSONResponse(
        {"error": "Google sign-in is not configured."},
        status_code=404,
    )


async def start(request: Request) -> Response:
    missing = _configured_response()
    if missing is not None:
        return missing
    try:
        redirect = await _client().authorize_redirect(request, redirect_uri())
    except Exception as exc:
        logger.info("Google sign-in could not start: %s", type(exc).__name__)
        return JSONResponse({"error": "Google sign-in failed."}, status_code=400)
    location = redirect.headers.get("location", "")
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"url": location})
    return redirect


def _rejected(exc: Exception) -> JSONResponse:
    from authlib.integrations.base_client.errors import OAuthError
    from authlib.jose.errors import JoseError

    logger.info("Google sign-in rejected: %s", type(exc).__name__)
    if isinstance(exc, (OAuthError, JoseError)):
        return JSONResponse(
            {"error": "Google sign-in could not be verified. Start again."},
            status_code=400,
        )
    return JSONResponse({"error": "Google sign-in failed."}, status_code=400)


async def finish(request: Request) -> JSONResponse:
    missing = _configured_response()
    if missing is not None:
        return missing
    client_id = google_client_id()
    try:
        token = await _client().authorize_access_token(
            request,
            claims_options={
                "iss": {"essential": True, "values": [GOOGLE_ISSUER]},
                "aud": {"essential": True, "values": [client_id]},
            },
        )
    except Exception as exc:
        return _rejected(exc)

    userinfo = token.get("userinfo") or {}
    if userinfo.get("email_verified") is not True:
        logger.info("Google sign-in rejected: email_verified")
        return JSONResponse(
            {"error": "Google has not verified this email address."},
            status_code=403,
        )
    email = str(userinfo.get("email") or "")
    subject = str(userinfo.get("sub") or "")
    if not email or not subject:
        return JSONResponse(
            {"error": "Google did not return a verified email."},
            status_code=403,
        )
    try:
        session = auth.login_with_google(email, subject)
    except auth.AuthError as exc:
        return JSONResponse({"error": exc.message}, status_code=exc.status_code)
    return JSONResponse(session)
