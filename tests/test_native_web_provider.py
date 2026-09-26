from __future__ import annotations

from datetime import UTC, datetime

import pytest

from internet_hands.capability_economics import estimate_call, settle_measured_cost
from internet_hands.execution_meter import (
    execution_usage_snapshot,
    reset_execution_meter,
    start_execution_meter,
)
from internet_hands.models import FetchResult
from internet_hands.native_web_provider import NativeWebToolProvider
from internet_hands.tool_mesh import ToolMesh


class _Dumpable:
    def __init__(self, payload: dict):
        self.payload = payload

    def model_dump(self, *, mode: str = "python") -> dict:
        assert mode == "json"
        return self.payload


@pytest.mark.asyncio
async def test_native_web_provider_is_always_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    provider = NativeWebToolProvider()
    status = await provider.status()
    assert status["configured"] is True
    assert status["searchable"] is True
    assert status["executable"] is True
    assert status["search_configured"] is False


@pytest.mark.asyncio
async def test_native_fetch_executes_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(url: str, **_kwargs):
        return _Dumpable({"final_url": url, "status_code": 200, "body_text": "ok"})

    monkeypatch.setattr("internet_hands.native_web_provider.fetch_url", fake_fetch)
    provider = NativeWebToolProvider()
    result = await provider.execute("fetch", {"url": "https://example.com"})
    assert result["status"] == "completed"
    assert result["data"]["status_code"] == 200


@pytest.mark.asyncio
async def test_native_search_uses_brave_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search(query: str, **_kwargs):
        return {"provider": "brave", "query": query, "response": {"web": {"results": []}}}

    monkeypatch.setattr("internet_hands.native_web_provider.brave_search", fake_search)
    provider = NativeWebToolProvider()
    result = await provider.execute("search", {"query": "internet hands"})
    assert result["status"] == "completed"
    assert result["data"]["provider"] == "brave"


@pytest.mark.asyncio
async def test_native_crawl_accepts_firecrawl_limit_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    async def fake_crawl(url: str, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return _Dumpable({"seed_url": url, "pages": [], "truncated": False})

    monkeypatch.setattr("internet_hands.native_web_provider.crawl", fake_crawl)
    provider = NativeWebToolProvider()
    result = await provider.execute(
        "crawl", {"url": "https://example.com", "limit": 7, "max_depth": 2}
    )
    assert result["status"] == "completed"
    assert seen["max_pages"] == 7
    assert seen["max_depth"] == 2


@pytest.mark.asyncio
async def test_native_batch_fetch_isolates_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(url: str, **_kwargs):
        if url.endswith("/bad"):
            raise RuntimeError("boom")
        return _Dumpable({"final_url": url, "status_code": 200})

    monkeypatch.setattr("internet_hands.native_web_provider.fetch_url", fake_fetch)
    provider = NativeWebToolProvider()
    result = await provider.execute(
        "batch-fetch",
        {"urls": ["https://example.com/ok", "https://example.com/bad"]},
    )
    rows = result["data"]["results"]
    assert rows[0]["status"] == "completed"
    assert rows[1]["status"] == "failed"


def test_native_provider_exposes_five_bounded_tools() -> None:
    provider = NativeWebToolProvider()
    assert set(provider._descriptors()) == {
        "fetch",
        "search",
        "map",
        "crawl",
        "batch-fetch",
    }
    assert all(not row.side_effecting for row in provider._descriptors().values())


@pytest.mark.asyncio
async def test_native_batch_reserves_per_url_and_charges_failed_attempts(monkeypatch):
    async def fake_fetch(url, **kwargs):
        if url.endswith("bad"):
            raise RuntimeError("source unavailable")
        return _Dumpable({"final_url": url, "status_code": 200})

    monkeypatch.setattr("internet_hands.native_web_provider.fetch_url", fake_fetch)
    arguments = {"ref": "nativeweb:batch-fetch", "arguments": {"urls": ["https://example.com/ok", "https://example.com/bad"]}}
    quote = estimate_call("mesh_execute", arguments, "free")
    assert quote.allowed and quote.credits == 8
    token = start_execution_meter()
    try:
        result = await ToolMesh([NativeWebToolProvider()]).execute(arguments["ref"], arguments["arguments"])
        usage = execution_usage_snapshot()
    finally:
        reset_execution_meter(token)
    assert result["status"] == "completed"
    assert usage["counters"]["native_web_requests"] == 2
    assert settle_measured_cost("mesh_execute", arguments, "free", reserved_credits=quote.credits, execution_usage=usage) == 8
    crawl = estimate_call("mesh_execute", {"ref": "nativeweb:crawl", "arguments": {"max_pages": 500}}, "free")
    assert crawl.allowed and crawl.credits == 3002
    assert not estimate_call("mesh_execute", {"ref": "nativeweb:batch-fetch", "arguments": {"urls": []}}, "free").allowed


@pytest.mark.asyncio
async def test_native_crawl_counts_robots_and_pages_and_guards_redirects(monkeypatch):
    from internet_hands import crawler

    visited = []

    async def fake_fetch(url, **kwargs):
        visited.append(url)
        if "url_guard" in kwargs:
            assert not kwargs["url_guard"]("https://elsewhere.example/private")
        body = ("User-agent: *\nDisallow: /private" if url.endswith("robots.txt") else
                '<a href="/next">Next</a><a href="/private">Blocked</a>' if url.endswith("/") else "Done")
        return FetchResult(request_url=url, final_url=url, status_code=200, headers={},
                           content_type="text/html" if not url.endswith("robots.txt") else "text/plain",
                           content_length=len(body), sha256="fixture", elapsed_ms=1,
                           captured_at=datetime.now(UTC), body_text=body)

    monkeypatch.setattr(crawler, "validate_public_http_url", lambda url: url)
    monkeypatch.setattr(crawler, "fetch_url", fake_fetch)
    call = {"ref": "nativeweb:crawl", "arguments": {"url": "https://example.com/", "max_pages": 3, "max_depth": 1}}
    quote = estimate_call("mesh_execute", call, "free")
    token = start_execution_meter()
    try:
        result = await ToolMesh([NativeWebToolProvider()]).execute(call["ref"], call["arguments"])
        usage = execution_usage_snapshot()
    finally:
        reset_execution_meter(token)
    assert result["status"] == "completed"
    assert "https://example.com/private" not in visited
    assert usage["counters"]["native_web_requests"] == len(visited) == 3
    assert settle_measured_cost("mesh_execute", call, "free", reserved_credits=quote.credits, execution_usage=usage) == 11
