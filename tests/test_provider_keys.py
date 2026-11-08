import asyncio

import pytest
from langchain_core.runnables.config import var_child_runnable_config

import gsb_chef
import server_auth
from provider_keys import (
    MissingAPIKeyError,
    lookup_provider_keys,
    resolve_api_key,
    stash_provider_keys,
)

OPENAI_KEY = "sk-request-openai-ZZ99"
TAVILY_KEY = "tvly-request-tavily-QQ77"


def _use_key_id(key_id: str):
    return var_child_runnable_config.set(
        {"configurable": {"langgraph_auth_user": {"provider_key_id": key_id}}}
    )


def test_authenticate_keeps_secrets_out_of_the_user(monkeypatch):
    monkeypatch.delenv("GSB_PROVIDER_KEY_TTL_SECONDS", raising=False)

    async def run():
        return await server_auth.authenticate(
            {
                b"x-openai-api-key": OPENAI_KEY.encode(),
                b"x-tavily-api-key": TAVILY_KEY.encode(),
            }
        )

    user = asyncio.run(run())
    assert OPENAI_KEY not in str(user)
    assert TAVILY_KEY not in str(user)
    stored = lookup_provider_keys(user["provider_key_id"])
    assert stored["openai_api_key"] == OPENAI_KEY
    assert stored["tavily_api_key"] == TAVILY_KEY


def test_request_key_is_preferred_and_missing_key_is_clear(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-openai-AAAA")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-env-tavily-BBBB")
    key_id = stash_provider_keys(openai_api_key=OPENAI_KEY, tavily_api_key="")
    token = _use_key_id(key_id)
    try:
        assert resolve_api_key("openai_api_key", "OPENAI_API_KEY") == (OPENAI_KEY, "request")
        assert resolve_api_key("tavily_api_key", "TAVILY_API_KEY") == (
            "tvly-env-tavily-BBBB",
            "environment",
        )
    finally:
        var_child_runnable_config.reset(token)

    empty = var_child_runnable_config.set({"configurable": {}})
    monkeypatch.delenv("OPENAI_API_KEY")
    try:
        with pytest.raises(MissingAPIKeyError) as exc:
            resolve_api_key("openai_api_key", "OPENAI_API_KEY")
    finally:
        var_child_runnable_config.reset(empty)
    assert "OPENAI_API_KEY is missing" in str(exc.value)
    assert "chat settings" in str(exc.value)


def test_stashed_keys_expire(monkeypatch):
    monkeypatch.setenv("GSB_PROVIDER_KEY_TTL_SECONDS", "0")
    key_id = stash_provider_keys(openai_api_key=OPENAI_KEY, tavily_api_key=TAVILY_KEY)
    assert lookup_provider_keys(key_id) == {}


def test_web_search_reports_the_request_key(monkeypatch):
    class FakeTavily:
        def __init__(self, api_key: str):
            self.api_key = api_key

        def search(self, query: str):
            assert self.api_key == TAVILY_KEY
            raise RuntimeError(f"rejected {self.api_key}")

    monkeypatch.setattr(gsb_chef, "TavilyClient", FakeTavily)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    key_id = stash_provider_keys(openai_api_key="", tavily_api_key=TAVILY_KEY)
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            gsb_chef.web_search.ainvoke(
                {"query": "rice and coconut"},
                config={
                    "configurable": {"langgraph_auth_user": {"provider_key_id": key_id}}
                },
            )
        )
    message = str(exc.value)
    assert "request API key ending in QQ77" in message
    assert TAVILY_KEY not in message


def test_model_middleware_reports_the_request_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    key_id = stash_provider_keys(openai_api_key=OPENAI_KEY, tavily_api_key="")
    token = _use_key_id(key_id)
    seen = []

    class Request:
        def override(self, *, model):
            seen.append(model)
            return self

    async def handler(request):
        raise RuntimeError("rejected by model")

    try:
        with pytest.raises(RuntimeError) as exc:
            asyncio.run(gsb_chef._apply_openai_api_key(Request(), handler))
    finally:
        var_child_runnable_config.reset(token)
    secret = seen[0].openai_api_key
    revealed = secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret)
    assert revealed == OPENAI_KEY
    assert "request API key ending in ZZ99" in str(exc.value)
    assert OPENAI_KEY not in str(exc.value)
