from langgraph_sdk import Auth

from provider_keys import stash_provider_keys

auth = Auth()


def _header(headers: dict, name: str) -> str:
    raw = headers.get(name.encode())
    if raw is None:
        raw = headers.get(name)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        return ""
    return raw.strip()


@auth.authenticate
async def authenticate(headers: dict) -> dict:
    """Accept local requests and keep provider keys out of stored run config.

    The LangGraph dev server writes run config to disk. Keys sent on these
    headers are held only in process memory, under an id stored on the user.
    """
    openai_api_key = _header(headers, "x-openai-api-key")
    tavily_api_key = _header(headers, "x-tavily-api-key")
    user: dict[str, str] = {"identity": "local"}
    if openai_api_key or tavily_api_key:
        user["provider_key_id"] = stash_provider_keys(
            openai_api_key=openai_api_key,
            tavily_api_key=tavily_api_key,
        )
    return user
