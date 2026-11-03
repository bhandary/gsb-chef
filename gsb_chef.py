import os
from typing import Any

import anyio
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from tavily import TavilyClient

from provider_keys import MissingAPIKeyError, key_suffix, resolve_api_key

load_dotenv()
os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

MODEL_NAME = "gpt-5-nano"

system_prompt = """

You are a personal chef specializing in Gaud Saraswat Brahmin (GSB) Konkani cuisine. The user will give you a list of ingredients they have left over in their house.

Using the web search tool, search the web for recipes that can be made with the ingredients they have.

Return recipe suggestions and eventually the recipe instructions to the user, if requested.

"""


@tool
async def web_search(query: str) -> dict[str, Any]:
    """Search the web for information"""
    api_key, source = resolve_api_key("tavily_api_key", "TAVILY_API_KEY")

    def _search() -> dict[str, Any]:
        return TavilyClient(api_key=api_key).search(query)

    try:
        return await anyio.to_thread.run_sync(_search)
    except Exception as exc:
        raise RuntimeError(
            "Tavily search failed "
            f"({type(exc).__name__}) using the {source} API key ending in {key_suffix(api_key)}."
        ) from None


async def _apply_openai_api_key(request, handler):
    api_key, source = resolve_api_key("openai_api_key", "OPENAI_API_KEY")
    model = ChatOpenAI(model=MODEL_NAME, api_key=api_key)
    try:
        return await handler(request.override(model=model))
    except MissingAPIKeyError:
        raise
    except Exception as exc:
        raise RuntimeError(
            "OpenAI request failed "
            f"({type(exc).__name__}) using the {source} API key ending in {key_suffix(api_key)}."
        ) from None


apply_openai_api_key = wrap_model_call(_apply_openai_api_key)

agent = create_agent(
    model=ChatOpenAI(model=MODEL_NAME, api_key="not-a-request-key"),
    tools=[web_search],
    system_prompt=system_prompt,
    middleware=[apply_openai_api_key],
)
