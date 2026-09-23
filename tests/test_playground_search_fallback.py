from __future__ import annotations

import asyncio

import internet_hands.playground_api as playground


class _Firecrawl:
    api_key = "configured"

    async def execute(self, tool_id, arguments, **kwargs):
        assert tool_id == "search"
        return {
            "data": {
                "web": [
                    {
                        "url": "https://example.com/about",
                        "title": "Example",
                        "description": "Company overview",
                        "markdown": "Example company overview. " * 30,
                    }
                ]
            },
            "metadata": {"credits_used": 2},
        }


def test_search_falls_back_to_firecrawl_when_brave_fails(monkeypatch) -> None:
    async def fail_brave(*args, **kwargs):
        raise RuntimeError("missing Brave key")

    monkeypatch.setattr(playground, "brave_search", fail_brave)
    monkeypatch.setattr(playground, "FirecrawlToolProvider", _Firecrawl)

    sources, meta = asyncio.run(
        playground._discover_search_sources("example company", count=5, timeout=10)
    )
    assert meta["provider"] == "firecrawl"
    assert meta["fallback"] is True
    assert sources[0]["source"] == "firecrawl_search"
    assert sources[0]["prefetched_text"]


def test_research_evidence_reuses_firecrawl_search_markdown(monkeypatch) -> None:
    async def should_not_fetch(*args, **kwargs):
        raise AssertionError("native fetch should not run for substantial prefetched markdown")

    monkeypatch.setattr(playground, "fetch_url", should_not_fetch)
    source = {
        "url": "https://example.com/about",
        "title": "Example",
        "description": "Company overview",
        "source": "firecrawl_search",
        "rank": 1,
        "prefetched_text": "Useful source-backed content. " * 30,
    }
    evidence = asyncio.run(playground._research_evidence([source], limit=1, timeout=5))
    assert evidence[0]["source"] == "firecrawl_search"
    assert evidence[0]["discovery_source"] == "firecrawl_search"
    assert len(evidence[0]["text"]) >= 280
