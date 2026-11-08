import os
import time
from threading import Lock

from langgraph.config import get_config

_LOCK = Lock()
_STORE: dict[str, tuple[float, dict[str, str]]] = {}
_DEFAULT_TTL_SECONDS = 900


class MissingAPIKeyError(ValueError):
    pass


def _ttl_seconds() -> float:
    raw = os.getenv("GSB_PROVIDER_KEY_TTL_SECONDS", str(_DEFAULT_TTL_SECONDS))
    return float(raw)


def stash_provider_keys(*, openai_api_key: str, tavily_api_key: str) -> str:
    """Remember request keys in process memory and return a non-secret id."""
    import secrets

    key_id = secrets.token_urlsafe(18)
    expires_at = time.monotonic() + _ttl_seconds()
    now = time.monotonic()
    with _LOCK:
        expired = [item_id for item_id, (expiry, _) in _STORE.items() if expiry <= now]
        for item_id in expired:
            del _STORE[item_id]
        _STORE[key_id] = (
            expires_at,
            {
                "openai_api_key": openai_api_key,
                "tavily_api_key": tavily_api_key,
            },
        )
    return key_id


def lookup_provider_keys(key_id: str) -> dict[str, str]:
    now = time.monotonic()
    with _LOCK:
        item = _STORE.get(key_id)
        if item is None:
            return {}
        expires_at, keys = item
        if expires_at <= now:
            del _STORE[key_id]
            return {}
        return dict(keys)


def key_suffix(api_key: str) -> str:
    if len(api_key) < 8:
        return "****"
    return api_key[-4:]


def _provider_key_id(user: object) -> str:
    if user is None:
        return ""
    value = None
    if isinstance(user, dict):
        value = user.get("provider_key_id")
    else:
        value = getattr(user, "provider_key_id", None)
        if value is None and hasattr(user, "get"):
            value = user.get("provider_key_id")
    if isinstance(value, str):
        return value.strip()
    return ""


def request_provider_keys() -> dict[str, str]:
    try:
        config = get_config()
    except RuntimeError:
        return {}
    configurable = config.get("configurable") or {}
    key_id = _provider_key_id(configurable.get("langgraph_auth_user"))
    if not key_id:
        return {}
    return lookup_provider_keys(key_id)


def resolve_api_key(config_name: str, env_name: str) -> tuple[str, str]:
    """Return the request key, or the environment key, and where it came from."""
    request_value = (request_provider_keys().get(config_name) or "").strip()
    if request_value:
        return request_value, "request"
    env_value = (os.getenv(env_name) or "").strip()
    if env_value:
        return env_value, "environment"
    raise MissingAPIKeyError(
        f"{env_name} is missing. Enter it in the chat settings or set {env_name} in the environment."
    )
