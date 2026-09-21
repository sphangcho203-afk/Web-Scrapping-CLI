from __future__ import annotations

from types import SimpleNamespace

import pytest

from internet_hands.native_web_provider import NativeWebToolProvider


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
