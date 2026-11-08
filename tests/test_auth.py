import logging
import os
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

import auth
from auth_app import app


@pytest.fixture()
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("GSB_AUTH_DB", str(tmp_path / "auth.db"))
    monkeypatch.delenv("GSB_VERIFICATION_TTL_SECONDS", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:3000")
    return tmp_path / "auth.db"


def test_password_is_hashed_with_argon2id():
    first = auth.hash_password("correct horse battery")
    second = auth.hash_password("correct horse battery")
    assert first.startswith("$argon2id$")
    assert second.startswith("$argon2id$")
    assert first != second
    assert "correct horse battery" not in first
    assert auth.verify_password(first, "correct horse battery")
    assert not auth.verify_password(first, "wrong password")


def _token_from_log(caplog) -> str:
    for record in caplog.records:
        message = record.getMessage()
        marker = "#token="
        if marker in message:
            return message.split(marker, 1)[1].strip()
    raise AssertionError("verification link was not logged")


def test_verification_succeeds_and_stores_token_hashed(database, caplog):
    caplog.set_level(logging.INFO, logger="gsb.auth")
    password = "pantry-secret-1"
    result = auth.signup("Cook@Example.com", password)
    assert result["delivery"] == "log"
    assert password not in caplog.text

    token = _token_from_log(caplog)
    conn = auth.connect()
    try:
        row = conn.execute(
            "SELECT token_hash FROM email_verification_tokens"
        ).fetchone()
        assert row["token_hash"] == auth.hash_token(token)
        assert token not in row["token_hash"]
    finally:
        conn.close()

    verified = auth.verify_email_token(token)
    assert verified["email"] == "cook@example.com"
    assert database.read_bytes().find(token.encode()) == -1
    assert database.read_bytes().find(verified["token"].encode()) == -1
    assert database.read_bytes().find(password.encode()) == -1
    user = auth.current_user(verified["token"])
    assert user["email"] == "cook@example.com"


def test_verification_token_cannot_be_reused(database, caplog):
    caplog.set_level(logging.INFO, logger="gsb.auth")
    auth.signup("cook@example.com", "pantry-secret-1")
    token = _token_from_log(caplog)
    auth.verify_email_token(token)
    with pytest.raises(auth.AuthError) as exc:
        auth.verify_email_token(token)
    assert exc.value.code == "used"
    assert exc.value.message == "This verification link has already been used."


def test_expired_verification_token_is_rejected(database, monkeypatch):
    monkeypatch.setenv("GSB_VERIFICATION_TTL_SECONDS", "60")
    issued_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    conn = auth.connect()
    try:
        conn.execute(
            """
            INSERT INTO users (email, password_hash, email_verified_at, created_at)
            VALUES (?, ?, NULL, ?)
            """,
            ("cook@example.com", auth.hash_password("pantry-secret-1"), issued_at.isoformat()),
        )
        conn.commit()
        user_id = conn.execute("SELECT id FROM users").fetchone()["id"]
        token = auth.issue_verification_token(conn, user_id, now=issued_at)
    finally:
        conn.close()

    with pytest.raises(auth.AuthError) as exc:
        auth.verify_email_token(token, now=issued_at + timedelta(seconds=61))
    assert exc.value.code == "expired"
    assert exc.value.message == "This verification link has expired."


def test_http_signup_and_verification(database, caplog):
    caplog.set_level(logging.INFO, logger="gsb.auth")
    client = TestClient(app)
    password = "pantry-secret-1"
    created = client.post(
        "/auth/signup",
        json={"email": "cook@example.com", "password": password},
    )
    assert created.status_code == 201
    assert created.json() == {"ok": True, "delivery": "log"}
    assert password not in created.text
    assert "#token=" not in created.text

    token = _token_from_log(caplog)
    verified = client.post("/auth/verify", json={"token": token})
    assert verified.status_code == 200
    body = verified.json()
    assert body["ok"] is True
    assert body["email"] == "cook@example.com"
    session = body["token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {session}"})
    assert me.status_code == 200
    assert me.json() == {"email": "cook@example.com"}

    reused = client.post("/auth/verify", json={"token": token})
    assert reused.status_code == 400
    assert reused.json()["error"] == "This verification link has already been used."


def test_http_expired_token_is_rejected(database, caplog, monkeypatch):
    monkeypatch.setenv("GSB_VERIFICATION_TTL_SECONDS", "0")
    caplog.set_level(logging.INFO, logger="gsb.auth")
    client = TestClient(app)
    created = client.post(
        "/auth/signup",
        json={"email": "cook@example.com", "password": "pantry-secret-1"},
    )
    assert created.status_code == 201
    token = _token_from_log(caplog)
    rejected = client.post("/auth/verify", json={"token": token})
    assert rejected.status_code == 400
    assert rejected.json()["error"] == "This verification link has expired."
