from __future__ import annotations

import json

import httpx
import pytest

from internet_hands.firecrawl_provider import FirecrawlToolProvider


def _disable_public_url_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "internet_hands.firecrawl_provider.validate_public_http_url",
        lambda _url: None,
    )


@pytest.mark.asyncio
async def test_firecrawl_catalog_is_discoverable_without_key() -> None:
    provider = FirecrawlToolProvider(api_key="")
    status = await provider.status()
    assert status["searchable"] is True
    assert status["executable"] is False
    assert status["api"] == "v2"
    assert status["tool_count"] >= 8

    tools = await provider.search("crawl website", limit=5)
    assert any(tool.ref == "firecrawl:crawl" for tool in tools)


@pytest.mark.asyncio
async def test_firecrawl_descriptor_never_contains_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-secret-value")
    provider = FirecrawlToolProvider()
    descriptor = await provider.describe("scrape")
    serialized = json.dumps(descriptor.to_dict())
    assert "fc-secret-value" not in serialized
    assert descriptor.side_effecting is False

    interact = await provider.describe("interact")
    assert interact.side_effecting is True


@pytest.mark.asyncio
async def test_firecrawl_scrape_uses_v2_and_server_side_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_public_url_validation(monkeypatch)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v2/scrape"
        assert request.headers["authorization"] == "Bearer fc-test"
        body = json.loads(request.content)
        assert body["url"] == "https://example.com"
        assert body["formats"] == ["markdown"]
        return httpx.Response(
            200,
            json={
                "success": True,
                "id": "scrape-1",
                "data": {"markdown": "# Example"},
                "creditsUsed": 1,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = FirecrawlToolProvider(api_key="fc-test", client=client)
        result = await provider.execute(
            "scrape",
            {"url": "https://example.com", "formats": ["markdown"]},
        )

    assert result["status"] == "completed"
    assert result["data"]["markdown"] == "# Example"
    assert result["metadata"]["scrape_id"] == "scrape-1"


@pytest.mark.asyncio
async def test_firecrawl_crawl_job_polling_and_paged_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_public_url_validation(monkeypatch)
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        assert request.headers["authorization"] == "Bearer fc-test"
        if request.method == "POST":
            assert request.url.path == "/v2/crawl"
            return httpx.Response(200, json={"success": True, "id": "crawl-123"})
        assert request.url.path == "/v2/crawl/crawl-123"
        if request.url.params:
            assert request.url.params["skip"] == "25"
            assert request.url.params["limit"] == "10"
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "total": 40,
                    "completed": 40,
                    "data": [{"markdown": "page"}],
                    "next": None,
                },
            )
        return httpx.Response(
            200,
            json={"status": "completed", "total": 40, "completed": 40},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = FirecrawlToolProvider(api_key="fc-test", client=client)
        started = await provider.execute(
            "crawl",
            {"url": "https://example.com", "limit": 40},
            wait_seconds=0,
        )
        assert started["status"] == "running"
        assert started["job_id"] == "crawl:crawl-123"
        assert started["result_id"] == "crawl:crawl-123"

        status = await provider.job_status("crawl:crawl-123")
        page = await provider.result_page("crawl:crawl-123", offset=25, limit=10)

    assert status["meshStatus"] == "completed"
    assert page["items"] == [{"markdown": "page"}]
    assert calls == [
        "POST /v2/crawl",
        "GET /v2/crawl/crawl-123",
        "GET /v2/crawl/crawl-123",
    ]


@pytest.mark.asyncio
async def test_firecrawl_batch_and_agent_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_public_url_validation(monkeypatch)
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/v2/batch/scrape":
            return httpx.Response(200, json={"success": True, "id": "batch-1"})
        if request.url.path == "/v2/agent":
            return httpx.Response(200, json={"success": True, "id": "agent-1"})
        if request.url.path == "/v2/agent/agent-1":
            return httpx.Response(200, json={"status": "completed", "data": {"answer": "ok"}})
        raise AssertionError(f"unexpected route: {request.url.path}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = FirecrawlToolProvider(api_key="fc-test", client=client)
        batch = await provider.execute(
            "batch-scrape",
            {"urls": ["https://example.com/a", "https://example.com/b"]},
            wait_seconds=0,
        )
        agent = await provider.execute(
            "agent",
            {"prompt": "Research example.com"},
            wait_seconds=0,
        )
        status = await provider.job_status(agent["job_id"])

    assert batch["job_id"] == "batch-scrape:batch-1"
    assert agent["job_id"] == "agent:agent-1"
    assert status["meshStatus"] == "completed"
    assert seen == ["/v2/batch/scrape", "/v2/agent", "/v2/agent/agent-1"]


@pytest.mark.asyncio
async def test_firecrawl_interact_is_explicit_and_prompt_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/scrape/scrape-42/interact"
        body = json.loads(request.content)
        assert body == {"prompt": "Open the details panel"}
        return httpx.Response(200, json={"success": True, "result": "done"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = FirecrawlToolProvider(api_key="fc-test", client=client)
        descriptor = await provider.describe("interact")
        assert descriptor.side_effecting is True
        result = await provider.execute(
            "interact",
            {"scrape_id": "scrape-42", "prompt": "Open the details panel"},
        )
        assert result["status"] == "completed"

        with pytest.raises(PermissionError, match="prompt-only"):
            await provider.execute(
                "interact",
                {"scrape_id": "scrape-42", "prompt": "x", "code": "process.exit()"},
            )


@pytest.mark.asyncio
async def test_firecrawl_read_only_scrape_rejects_actions_and_sensitive_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_public_url_validation(monkeypatch)
    provider = FirecrawlToolProvider(api_key="fc-test")

    with pytest.raises(PermissionError, match="does not accept actions"):
        await provider.execute(
            "scrape",
            {"url": "https://example.com", "actions": [{"type": "click", "selector": "#buy"}]},
        )

    with pytest.raises(PermissionError, match="Authorization/Cookie/API-key"):
        await provider.execute(
            "scrape",
            {"url": "https://example.com", "headers": {"Cookie": "session=secret"}},
        )


@pytest.mark.asyncio
async def test_firecrawl_rejects_private_target_url() -> None:
    provider = FirecrawlToolProvider(api_key="fc-test")
    with pytest.raises((ValueError, PermissionError)):
        await provider.execute("scrape", {"url": "http://127.0.0.1/admin"})
