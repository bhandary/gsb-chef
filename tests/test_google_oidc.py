import json
import logging
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer

import pytest
from starlette.testclient import TestClient

import auth
from auth_app import app
from authlib.jose import JsonWebKey
from authlib.jose import jwt

CLIENT_ID = "test-client-id.apps.googleusercontent.com"
CLIENT_SECRET = "test-client-secret"
ISSUER = "https://accounts.google.com"

_PRIVATE = JsonWebKey.generate_key("RSA", 2048, is_private=True).as_dict(is_private=True)
_PRIVATE["kid"] = "test-key"
_PUBLIC = {name: _PRIVATE[name] for name in ("kty", "n", "e")}
_PUBLIC.update({"kid": "test-key", "alg": "RS256", "use": "sig"})


def _s256(verifier: str) -> str:
    import base64
    import hashlib

    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.path.startswith("/.well-known/openid-configuration"):
            body = json.dumps(self.server.config["discovery"]).encode()
        elif self.path.startswith("/jwks"):
            body = json.dumps({"keys": [_PUBLIC]}).encode()
        else:
            self._send(404, b"{}")
            return
        self._send(200, body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode()
        form = urllib.parse.parse_qs(raw)
        verifier = (form.get("code_verifier") or [""])[0]
        expected = self.server.config["code_challenge"]
        matched = bool(verifier) and _s256(verifier) == expected
        self.server.config["token_requests"] += 1
        self.server.config["verifier_matched"] = matched
        self.server.config["saw_basic"] = self.headers.get("Authorization", "").startswith(
            "Basic "
        )
        if not matched:
            self._send(400, b'{"error":"invalid_grant"}')
            return
        token = jwt.encode({"alg": "RS256", "kid": "test-key"}, self.server.config["claims"], _PRIVATE)
        if isinstance(token, bytes):
            token = token.decode()
        self.server.config["last_id_token"] = token
        payload = json.dumps(
            {
                "access_token": "mock-access-token",
                "token_type": "Bearer",
                "id_token": token,
            }
        ).encode()
        self._send(200, payload)

    def _send(self, status, body: bytes):
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _Server(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.config = {
            "discovery": {},
            "claims": {},
            "code_challenge": "",
            "token_requests": 0,
            "verifier_matched": False,
            "saw_basic": False,
            "last_id_token": "",
        }


@pytest.fixture()
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("GSB_AUTH_DB", str(tmp_path / "auth.db"))
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("APP_BASE_URL", "http://127.0.0.1:3000")
    return tmp_path / "auth.db"


@pytest.fixture()
def google(database, monkeypatch):
    server = _Server()
    port = server.server_address[1]
    server.config["discovery"] = {
        "issuer": ISSUER,
        "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_endpoint": f"http://127.0.0.1:{port}/token",
        "jwks_uri": f"http://127.0.0.1:{port}/jwks",
        "id_token_signing_alg_values_supported": ["RS256"],
    }
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv(
        "GOOGLE_DISCOVERY_URL",
        f"http://127.0.0.1:{port}/.well-known/openid-configuration",
    )
    try:
        yield server
    finally:
        server.shutdown()


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def _user_count():
    conn = auth.connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def _start(client):
    response = client.get("/auth/google/start", follow_redirects=False)
    assert response.status_code == 302, response.text
    parsed = urllib.parse.urlparse(response.headers["location"])
    query = urllib.parse.parse_qs(parsed.query)
    return parsed, query


def _claims(nonce, **overrides):
    now = int(time.time())
    body = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "google-sub-1",
        "email": "Cook@Example.com",
        "email_verified": True,
        "nonce": nonce,
        "iat": now,
        "exp": now + 600,
    }
    body.update(overrides)
    return body


def _callback(client, google, query, **overrides):
    nonce = overrides.pop("nonce", query["nonce"][0])
    google.config["claims"] = _claims(nonce, **overrides)
    google.config["code_challenge"] = query["code_challenge"][0]
    google.config["token_requests"] = 0
    google.config["last_id_token"] = ""
    return client.post(
        "/auth/google/callback",
        data={"code": "auth-code", "state": query["state"][0]},
    )


def _assert_authorize_url(parsed, query):
    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    assert parsed.path == "/o/oauth2/v2/auth"
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == ["http://127.0.0.1:3000/api/auth/google/callback"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0]
    assert query["state"][0]
    assert query["nonce"][0]
    assert query["state"][0] != query["nonce"][0]
    scope = query["scope"][0]
    assert "openid" in scope and "email" in scope


def test_google_button_is_hidden_without_a_client_id(database, client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    status = client.get("/auth/google")
    assert status.status_code == 200
    assert status.json() == {"enabled": False}
    start = client.get("/auth/google/start", follow_redirects=False)
    assert start.status_code == 404


def test_google_callback_signs_in_and_checks_pkce(google, client, caplog):
    caplog.set_level(logging.DEBUG)
    logging.getLogger("authlib").setLevel(logging.DEBUG)
    parsed, query = _start(client)
    _assert_authorize_url(parsed, query)
    described = client.get(
        "/auth/google/start",
        headers={"accept": "application/json"},
        follow_redirects=False,
    )
    assert described.status_code == 200
    described_url = urllib.parse.urlparse(described.json()["url"])
    described_query = urllib.parse.parse_qs(described_url.query)
    _assert_authorize_url(described_url, described_query)

    response = _callback(client, google, query)
    assert response.status_code == 200, response.text
    assert google.config["token_requests"] == 1
    assert google.config["verifier_matched"] is True
    assert google.config["saw_basic"] is True
    body = response.json()
    assert body["email"] == "cook@example.com"
    assert auth.current_user(body["token"])["email"] == "cook@example.com"
    conn = auth.connect()
    try:
        row = conn.execute(
            "SELECT email, password_hash, google_sub, email_verified_at FROM users"
        ).fetchone()
        used = conn.execute(
            "SELECT COUNT(*) FROM oauth_transactions WHERE cache_key = ?",
            (f"_state_google_{query['state'][0]}",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert row["email"] == "cook@example.com"
    assert row["google_sub"] == "google-sub-1"
    assert row["email_verified_at"]
    assert row["password_hash"] is None
    assert used == 0
    with pytest.raises(auth.AuthError):
        auth.login("cook@example.com", "pantry-secret-1")
    blob = database_bytes()
    assert CLIENT_SECRET.encode() not in blob
    assert google.config["last_id_token"].encode() not in blob
    assert b"mock-access-token" not in blob
    assert CLIENT_SECRET not in caplog.text
    assert "code_verifier" not in caplog.text.lower()
    assert "id_token" not in caplog.text.lower()
    assert "mock-access-token" not in caplog.text
    assert google.config["last_id_token"] not in caplog.text


def database_bytes():
    return auth.db_path().read_bytes()


def test_google_callback_rejects_a_bad_state(google, client):
    google.config["token_requests"] = 0
    response = client.post(
        "/auth/google/callback",
        data={"code": "auth-code", "state": "not-a-real-state"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "Google sign-in could not be verified. Start again."
    assert "auth-code" not in response.text
    assert google.config["token_requests"] == 0
    assert _user_count() == 0


def _assert_token_was_checked(google, response):
    assert google.config["token_requests"] == 1
    assert google.config["verifier_matched"] is True
    assert "auth-code" not in response.text
    assert _user_count() == 0


def test_google_callback_rejects_a_bad_nonce(google, client):
    _parsed, query = _start(client)
    response = _callback(client, google, query, nonce="wrong-nonce")
    assert response.status_code == 400
    _assert_token_was_checked(google, response)


def test_google_callback_rejects_the_wrong_audience(google, client):
    _parsed, query = _start(client)
    response = _callback(
        client, google, query, aud="someone-else.apps.googleusercontent.com"
    )
    assert response.status_code == 400
    _assert_token_was_checked(google, response)


def test_google_callback_rejects_an_expired_token(google, client):
    _parsed, query = _start(client)
    response = _callback(client, google, query, exp=int(time.time()) - 1000)
    assert response.status_code == 400
    _assert_token_was_checked(google, response)


def test_google_callback_rejects_an_unverified_email(google, client):
    _parsed, query = _start(client)
    response = _callback(client, google, query, email_verified=False)
    assert response.status_code == 403
    assert response.json()["error"] == "Google has not verified this email address."
    _assert_token_was_checked(google, response)


def test_google_login_links_an_existing_password_account(google, client, caplog):
    caplog.set_level(logging.INFO, logger="gsb.auth")
    password = "pantry-secret-1"
    auth.signup("cook@example.com", password)
    before = auth.connect()
    try:
        existing = before.execute(
            "SELECT id, password_hash, email_verified_at, google_sub FROM users"
        ).fetchone()
    finally:
        before.close()
    assert existing["email_verified_at"] is None
    assert existing["google_sub"] is None
    with pytest.raises(auth.AuthError) as blocked:
        auth.login("cook@example.com", password)
    assert blocked.value.status_code == 403

    _parsed, query = _start(client)
    response = _callback(client, google, query)
    assert response.status_code == 200, response.text
    after = auth.connect()
    try:
        linked = after.execute(
            "SELECT id, password_hash, email_verified_at, google_sub FROM users"
        ).fetchone()
    finally:
        after.close()
    assert linked["id"] == existing["id"]
    assert linked["password_hash"] == existing["password_hash"]
    assert linked["password_hash"].startswith("$argon2id$")
    assert linked["google_sub"] == "google-sub-1"
    assert linked["email_verified_at"]
    signed_in = auth.login("cook@example.com", password)
    assert signed_in["email"] == "cook@example.com"
    assert password.encode() not in database_bytes()


def test_legacy_password_column_can_store_a_google_only_user(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    monkeypatch.setenv("GSB_AUTH_DB", str(path))
    raw = __import__("sqlite3").connect(path)
    raw.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            email_verified_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    raw.commit()
    raw.close()
    result = auth.login_with_google("legacy@example.com", "sub-legacy")
    assert auth.current_user(result["token"])["email"] == "legacy@example.com"
    conn = auth.connect()
    try:
        row = conn.execute(
            "SELECT password_hash, google_sub FROM users"
        ).fetchone()
    finally:
        conn.close()
    assert row["google_sub"] == "sub-legacy"
    assert row["password_hash"].startswith("$argon2id$")
    with pytest.raises(auth.AuthError):
        auth.login("legacy@example.com", "pantry-secret-1")
