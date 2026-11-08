import os
import uuid
from typing import Any


class FeedbackError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        self.message = message
        self.status_code = status_code


def feedback_configured() -> bool:
    tracing = os.getenv("LANGSMITH_TRACING", "").strip().lower()
    key = os.getenv("LANGSMITH_API_KEY", "").strip()
    return tracing in {"1", "true", "yes"} and bool(key)


def _parse_uuid(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return None
    return str(parsed)


def _client() -> Any:
    from langsmith import Client

    return Client()


def handle_feedback(
    trace_id: str | None,
    reaction: str | None,
    client: Any | None = None,
) -> Any:
    """Call this from the UI when a user clicks thumbs up or down.

    An empty reaction logs nothing. ``liked`` scores 1 and ``disliked``
    scores 0, both under the key ``user_sentiment``. ``trace_id`` is the
    LangGraph run id, which LangSmith uses as the trace id when tracing is on.
    """
    if not reaction:
        return None
    if reaction not in {"liked", "disliked"}:
        raise FeedbackError("reaction must be liked or disliked.", 400)
    parsed = _parse_uuid(trace_id)
    if parsed is None:
        raise FeedbackError("trace_id must be a UUID.", 400)
    if not feedback_configured():
        raise FeedbackError("feedback not configured", 503)
    langsmith = client if client is not None else _client()
    try:
        return langsmith.create_feedback(
            key="user_sentiment",
            score=1 if reaction == "liked" else 0,
            trace_id=parsed,
        )
    except Exception as exc:
        raise FeedbackError(
            f"LangSmith feedback failed ({type(exc).__name__}).",
            502,
        ) from None
