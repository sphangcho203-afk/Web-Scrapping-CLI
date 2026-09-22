from __future__ import annotations

import asyncio

import internet_hands.playground_api as playground


class _Firecrawl:
    api_key = "configured"
    last_arguments = None

    async def execute(self, tool_id, arguments, **kwargs):
        type(self).last_arguments = dict(arguments)
        return {
            "data": {"web": [{"url": "https://example.com", "title": "Example", "description": "Overview"}]},
            "metadata": {"credits_used": 1},
        }


def test_firecrawl_search_fallback_is_discovery_only_and_capped(monkeypatch) -> None:
    async def fail_brave(*args, **kwargs):
        raise RuntimeError("missing Brave key")

    monkeypatch.setattr(playground, "brave_search", fail_brave)
    monkeypatch.setattr(playground, "FirecrawlToolProvider", _Firecrawl)
    sources, meta = asyncio.run(
        playground._discover_search_sources("example company", count=50, timeout=30)
    )
    assert sources[0]["source"] == "firecrawl_search"
    assert _Firecrawl.last_arguments == {"query": "example company", "limit": 10}
    assert "scrapeOptions" not in _Firecrawl.last_arguments
    assert meta["provider"] == "firecrawl"
    assert meta["mode"] == "discovery_only"
    assert meta["result_limit"] == 10
