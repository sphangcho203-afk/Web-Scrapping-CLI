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
