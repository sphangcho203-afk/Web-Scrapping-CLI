from __future__ import annotations

import json

import httpx
import pytest

from internet_hands.research_brand_capabilities import build_research_brand_capabilities
from internet_hands.research_brand_providers import ExaToolProvider, TavilyToolProvider


@pytest.mark.asyncio
async def test_tavily_search_uses_server_side_bearer_and_bounded_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.tavily.com/search"
        assert request.headers["authorization"] == "Bearer tvly-secret"
        body = json.loads(request.content)
        assert body["query"] == "latest AI research"
        assert body["max_results"] == 20
        assert body["search_depth"] == "basic"
        assert body["safe_search"] is True
        assert body["include_usage"] is True
        assert "api_key" not in body
        assert "unexpected" not in body
        return httpx.Response(
            200,
            json={
                "results": [{"title": "A", "url": "https://example.com"}],
                "usage": {"credits": 1},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = TavilyToolProvider(api_key="tvly-secret", client=client)
        result = await provider.execute(
            "search",
            {
                "query": "latest AI research",
                "max_results": 999,
                "unexpected": "drop-me",
            },
        )

    assert result["status"] == "completed"
    assert result["metadata"]["credits_used"] == 1


@pytest.mark.asyncio
async def test_tavily_crawl_defaults_external_traversal_off() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.tavily.com/crawl"
        body = json.loads(request.content)
        assert body["url"] == "https://docs.example.com"
        assert body["allow_external"] is False
        assert body["limit"] == 100
        assert body["max_depth"] == 5
        assert body["max_breadth"] == 100
        return httpx.Response(200, json={"results": [], "usage": {"credits": 2}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = TavilyToolProvider(api_key="tvly-secret", client=client)
        result = await provider.execute(
            "crawl",
            {
                "url": "https://docs.example.com",
                "limit": 999,
                "max_depth": 99,
                "max_breadth": 999,
            },
        )

    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_exa_search_nests_content_options_and_keeps_key_server_side() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.exa.ai/search"
        assert request.headers["x-api-key"] == "exa-secret"
        body = json.loads(request.content)
        assert body["query"] == "agent systems"
        assert body["numResults"] == 25
        assert body["contents"] == {"text": True, "highlights": True, "summary": {}}
        assert "x-api-key" not in body
        return httpx.Response(
            200,
            json={
                "results": [],
                "costDollars": {"total": 0.007},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ExaToolProvider(api_key="exa-secret", client=client)
        result = await provider.execute(
            "search",
            {
                "query": "agent systems",
                "numResults": 1000,
                "text": True,
                "highlights": True,
                "summary": True,
            },
        )

    assert result["status"] == "completed"
    assert result["metadata"]["cost_dollars"] == 0.007


@pytest.mark.asyncio
async def test_exa_contents_rejects_non_public_urls() -> None:
    provider = ExaToolProvider(api_key="exa-secret")
    with pytest.raises((ValueError, RuntimeError)):
        await provider.execute(
            "contents",
            {"urls": ["http://127.0.0.1/private"], "text": True},
        )


def test_research_capabilities_expose_fallback_fabric() -> None:
    capabilities = {item.id: item for item in build_research_brand_capabilities()}
    assert {
        "web.search.semantic",
        "web.extract.urls",
        "web.map.smart",
        "web.crawl.smart",
    }.issubset(capabilities)
    search = capabilities["web.search.semantic"]
    assert [candidate.provider for candidate in search.candidates] == [
        "exa",
        "tavily",
        "firecrawl",
        "nativeweb",
    ]
    assert all(item.read_only for item in capabilities.values())
