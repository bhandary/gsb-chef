import logging

import pytest
from starlette.testclient import TestClient

import auth
from auth_app import app
import feedback

TRACE = "11111111-1111-4111-8111-111111111111"


PROJECT_ID = "22222222-2222-4222-8222-222222222222"


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create_feedback(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": "feedback"}


class ProjectClient(FakeClient):
    def __init__(self, project_id: str | None = PROJECT_ID, fail: bool = False) -> None:
        super().__init__()
        self.project_id = project_id
        self.fail = fail
        self.lookups: list[str | None] = []

    def read_project(self, *, project_name=None, **kwargs):
        self.lookups.append(project_name)
        if self.fail:
            raise RuntimeError("lookup failed")
        return type("Project", (), {"id": self.project_id})()


@pytest.fixture()
def database(tmp_path, monkeypatch):
    feedback._reset_project_cache()
    monkeypatch.setenv("GSB_AUTH_DB", str(tmp_path / "auth.db"))
    monkeypatch.delenv("GSB_VERIFICATION_TTL_SECONDS", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:3000")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-test")
    return tmp_path / "auth.db"


def _session(caplog) -> str:
    caplog.set_level(logging.INFO, logger="gsb.auth")
    client = TestClient(app)
    created = client.post(
        "/auth/signup",
        json={"email": "cook@example.com", "password": "pantry-secret-1"},
    )
    assert created.status_code == 201
    token = ""
    for record in caplog.records:
        message = record.getMessage()
        marker = "#token="
        if marker in message:
            token = message.split(marker, 1)[1].strip()
    assert token
    verified = client.post("/auth/verify", json={"token": token})
    assert verified.status_code == 200
    return verified.json()["token"]


def test_liked_scores_one(database):
    client = FakeClient()
    feedback.handle_feedback(TRACE, "liked", client=client)
    assert client.calls == [
        {"key": "user_sentiment", "score": 1, "trace_id": TRACE}
    ]


def test_disliked_scores_zero(database):
    client = FakeClient()
    feedback.handle_feedback(TRACE, "disliked", client=client)
    assert client.calls == [
        {"key": "user_sentiment", "score": 0, "trace_id": TRACE}
    ]


def test_empty_reaction_does_not_call_langsmith(database):
    client = FakeClient()
    assert feedback.handle_feedback(TRACE, None, client=client) is None
    assert feedback.handle_feedback(TRACE, "", client=client) is None
    assert feedback.handle_feedback("not-a-uuid", None, client=client) is None
    assert client.calls == []


def test_bad_input_is_rejected(database):
    client = FakeClient()
    with pytest.raises(feedback.FeedbackError) as bad_reaction:
        feedback.handle_feedback(TRACE, "love", client=client)
    assert bad_reaction.value.status_code == 400
    with pytest.raises(feedback.FeedbackError) as bad_trace:
        feedback.handle_feedback("not-a-uuid", "liked", client=client)
    assert bad_trace.value.status_code == 400
    assert "UUID" in bad_trace.value.message
    assert client.calls == []


def test_unconfigured_langsmith_does_not_call_the_client(database, monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    client = FakeClient()
    with pytest.raises(feedback.FeedbackError) as exc:
        feedback.handle_feedback(TRACE, "liked", client=client)
    assert exc.value.status_code == 503
    assert exc.value.message == "feedback not configured"
    assert client.calls == []


def test_session_id_is_the_project_id_and_the_lookup_is_cached(database, monkeypatch):
    monkeypatch.setenv("LANGSMITH_PROJECT", "gsb-chef")
    client = ProjectClient()
    feedback.handle_feedback(TRACE, "liked", client=client)
    feedback.handle_feedback(TRACE, "disliked", client=client)
    assert client.lookups == ["gsb-chef"]
    assert client.calls == [
        {
            "key": "user_sentiment",
            "score": 1,
            "trace_id": TRACE,
            "session_id": PROJECT_ID,
        },
        {
            "key": "user_sentiment",
            "score": 0,
            "trace_id": TRACE,
            "session_id": PROJECT_ID,
        },
    ]


def test_unset_project_uses_the_sdk_default_name(database, monkeypatch):
    for name in (
        "LANGSMITH_PROJECT",
        "LANGCHAIN_PROJECT",
        "LANGSMITH_SESSION",
        "LANGCHAIN_SESSION",
        "HOSTED_LANGSERVE_PROJECT_NAME",
    ):
        monkeypatch.delenv(name, raising=False)
    client = ProjectClient()
    feedback.handle_feedback(TRACE, "liked", client=client)
    assert client.lookups == ["default"]
    assert client.calls[0]["session_id"] == PROJECT_ID


def test_feedback_is_sent_when_the_project_lookup_fails(database, caplog):
    caplog.set_level(logging.WARNING, logger="gsb.feedback")
    client = ProjectClient(fail=True)
    feedback.handle_feedback(TRACE, "liked", client=client)
    feedback.handle_feedback(TRACE, "disliked", client=client)
    assert len(client.lookups) == 1
    assert client.calls == [
        {"key": "user_sentiment", "score": 1, "trace_id": TRACE},
        {"key": "user_sentiment", "score": 0, "trace_id": TRACE},
    ]
    assert any("project lookup failed" in record.getMessage() for record in caplog.records)


def test_unauthenticated_feedback_is_rejected(database):
    client = TestClient(app)
    rejected = client.post(
        "/feedback",
        json={"reaction": "liked", "trace_id": TRACE},
    )
    assert rejected.status_code == 401
    assert rejected.json() == {"error": "Sign in required."}


def test_http_feedback_uses_the_handler(database, caplog, monkeypatch):
    session = _session(caplog)
    fake = FakeClient()
    monkeypatch.setattr(feedback, "_client", lambda: fake)
    http = TestClient(app)
    logged = http.post(
        "/feedback",
        headers={"Authorization": f"Bearer {session}"},
        json={"reaction": "liked", "trace_id": TRACE},
    )
    assert logged.status_code == 200
    assert logged.json() == {"ok": True, "logged": True}
    assert fake.calls == [
        {"key": "user_sentiment", "score": 1, "trace_id": TRACE}
    ]

    cleared = http.post(
        "/feedback",
        headers={"Authorization": f"Bearer {session}"},
        json={"reaction": "", "trace_id": TRACE},
    )
    assert cleared.status_code == 200
    assert cleared.json() == {"ok": True, "logged": False}
    assert len(fake.calls) == 1

    rejected = http.post(
        "/feedback",
        headers={"Authorization": f"Bearer {session}"},
        json={"reaction": "liked", "trace_id": "nope"},
    )
    assert rejected.status_code == 400
    assert auth.current_user(session)["email"] == "cook@example.com"
