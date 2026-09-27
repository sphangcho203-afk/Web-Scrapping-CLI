from __future__ import annotations

from enum import StrEnum
from typing import Any

from .intel import _record, _request_json, _required_env


class SearchKind(StrEnum):
    WEB = "web"
    NEWS = "news"
    IMAGES = "images"
    VIDEOS = "videos"


ENDPOINTS = {
    SearchKind.WEB: "https://api.search.brave.com/res/v1/web/search",
    SearchKind.NEWS: "https://api.search.brave.com/res/v1/news/search",
    SearchKind.IMAGES: "https://api.search.brave.com/res/v1/images/search",
    SearchKind.VIDEOS: "https://api.search.brave.com/res/v1/videos/search",
}


async def brave_search(
    query: str,
    *,
    kind: SearchKind = SearchKind.WEB,
    count: int = 10,
    country: str | None = None,
    language: str | None = None,
    freshness: str | None = None,
) -> dict[str, Any]:
    query = query.strip()
    if not query:
        raise ValueError("query cannot be empty")
    if len(query) > 600 or len(query.split()) > 75:
        raise ValueError("query exceeds Brave Search API limits")

    endpoint = ENDPOINTS[kind]
    params: dict[str, Any] = {
        "q": query,
        "count": min(max(count, 1), 20),
        "safesearch": "strict",
    }
    if country:
        params["country"] = country.strip().upper()
    if language:
        params["search_lang"] = language.strip().lower()
    if freshness and kind in {SearchKind.WEB, SearchKind.NEWS}:
        params["freshness"] = freshness

    data = await _request_json(
        "GET",
        endpoint,
        headers={"X-Subscription-Token": _required_env("BRAVE_SEARCH_API_KEY")},
        params=params,
    )
    return _record(
        "brave",
        "search",
        query,
        endpoint,
        {
            "kind": kind.value,
            "safe_search": "strict",
            "response": data,
        },
    )

async def brave_llm_context(
    query: str,
    *,
    count: int = 20,
    country: str | None = None,
    language: str | None = None,
    freshness: str | None = None,
    maximum_number_of_urls: int = 20,
    maximum_number_of_tokens: int = 8192,
    maximum_number_of_snippets: int = 50,
    maximum_number_of_tokens_per_url: int = 4096,
    maximum_number_of_snippets_per_url: int = 50,
    context_threshold_mode: str = "balanced",
    enable_local: bool | None = None,
    enable_source_metadata: bool = True,
) -> dict[str, Any]:
    """Retrieve Brave's pre-extracted grounding context for an agent/RAG pipeline."""
    query = query.strip()
    if not query:
        raise ValueError("query cannot be empty")
    if len(query) > 400 or len(query.split()) > 50:
        raise ValueError("query exceeds Brave LLM Context limits")

    threshold = context_threshold_mode.strip().lower()
    if threshold not in {"strict", "balanced", "lenient", "disabled"}:
        raise ValueError(
            "context_threshold_mode must be strict, balanced, lenient, or disabled"
        )

    payload: dict[str, Any] = {
        "q": query,
        "count": min(max(int(count), 1), 50),
        "maximum_number_of_urls": min(max(int(maximum_number_of_urls), 1), 50),
        "maximum_number_of_tokens": min(max(int(maximum_number_of_tokens), 1024), 32768),
        "maximum_number_of_snippets": min(max(int(maximum_number_of_snippets), 1), 256),
        "maximum_number_of_tokens_per_url": min(
            max(int(maximum_number_of_tokens_per_url), 512), 8192
        ),
        "maximum_number_of_snippets_per_url": min(
            max(int(maximum_number_of_snippets_per_url), 1), 100
        ),
        "context_threshold_mode": threshold,
        "safesearch": "strict",
        "enable_source_metadata": bool(enable_source_metadata),
    }
    if country:
        payload["country"] = country.strip().upper()
    if language:
        payload["search_lang"] = language.strip().lower()
    if freshness:
        payload["freshness"] = freshness
    if enable_local is not None:
        payload["enable_local"] = bool(enable_local)

    endpoint = "https://api.search.brave.com/res/v1/llm/context"
    data = await _request_json(
        "POST",
        endpoint,
        headers={
            "X-Subscription-Token": _required_env("BRAVE_SEARCH_API_KEY"),
            "Content-Type": "application/json",
        },
        json_body=payload,
        timeout=30.0,
    )
    return _record(
        "brave",
        "llm-context",
        query,
        endpoint,
        {
            "safe_search": "strict",
            "response": data,
        },
    )

