import logging
import os
import uuid
from typing import Any

logger = logging.getLogger("gsb.feedback")

# Project id for create_feedback's session_id, resolved once per process.
_cached_session_id: str | None = None
_session_id_resolved = False


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


def _reset_project_cache() -> None:
    global _cached_session_id, _session_id_resolved
    _cached_session_id = None
    _session_id_resolved = False


def _project_name() -> str:
    """Name of the project the agent traces into.

    ``langsmith.utils.get_tracer_project`` reads ``LANGSMITH_PROJECT`` and,
    when that is unset, returns the SDK default project name.
    """
    from langsmith.utils import get_env_var, get_tracer_project

    # Both helpers cache environment reads. Clear them so this process sees
    # the env it was started with, then keep the id we look up.
    get_env_var.cache_clear()
    get_tracer_project.cache_clear()
    name = get_tracer_project()
    return name or "default"


def _tracing_session_id(client: Any) -> str | None:
    """LangSmith project id, cached for the life of the process.

    A failed lookup is cached too, so one click does not retry the API.
    Feedback is still sent without ``session_id`` in that case.
    """
    global _cached_session_id, _session_id_resolved
    if _session_id_resolved:
        return _cached_session_id
    _session_id_resolved = True
    try:
        project = client.read_project(project_name=_project_name())
        project_id = getattr(project, "id", None)
        if project_id is None and isinstance(project, dict):
            project_id = project.get("id")
        _cached_session_id = str(project_id) if project_id else None
    except Exception as exc:
        logger.warning(
            "LangSmith project lookup failed (%s); sending feedback without a project id.",
            type(exc).__name__,
        )
        _cached_session_id = None
        return None
    if not _cached_session_id:
        logger.warning(
            "LangSmith project lookup returned no id; sending feedback without a project id."
        )
    return _cached_session_id


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
    # session_id is the tracing project id. project_id cannot be combined
    # with trace_id in langsmith 0.14.17; omitting session_id is deprecated.
    session_id = _tracing_session_id(langsmith)
    payload: dict[str, Any] = {
        "key": "user_sentiment",
        "score": 1 if reaction == "liked" else 0,
        "trace_id": parsed,
    }
    if session_id:
        payload["session_id"] = session_id
    try:
        return langsmith.create_feedback(**payload)
    except Exception as exc:
        raise FeedbackError(
            f"LangSmith feedback failed ({type(exc).__name__}).",
            502,
        ) from None
