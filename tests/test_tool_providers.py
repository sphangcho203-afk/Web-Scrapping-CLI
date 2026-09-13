from __future__ import annotations

import json

import httpx
import pytest

from internet_hands.tool_providers import ApifyToolProvider, ComposioToolProvider


@pytest.mark.asyncio
async def test_apify_search_and_async_execute() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/store"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "items": [
                            {
                                "id": "actor1",
                                "username": "apify",
                                "name": "web-scraper",
                                "title": "Web Scraper",
                                "description": "Browser crawler",
                                "categories": ["WEB_SCRAPING"],
                            }
                        ]
                    }
                },
            )
        if request.url.path.endswith("/actors/apify~web-scraper/runs"):
            assert request.headers["authorization"] == "Bearer token"
            assert json.loads(request.content) == {
                "startUrls": [{"url": "https://example.com"}]
            }
            return httpx.Response(
                201,
                json={
                    "data": {
                        "id": "run1",
                        "status": "RUNNING",
                        "defaultDatasetId": "dataset1",
                    }
                },
            )
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ApifyToolProvider(
            token="token", base_url="https://api.test/v2", client=client
        )
        tools = await provider.search("web", limit=3)
        assert tools[0].ref == "apify:apify/web-scraper"
        result = await provider.execute(
            "apify/web-scraper",
            {"startUrls": [{"url": "https://example.com"}]},
            wait_seconds=0,
        )
        assert result["status"] == "running"
        assert result["job_id"] == "run1"
        assert result["result_id"] == "dataset1"


@pytest.mark.asyncio
async def test_apify_job_and_dataset_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/actor-runs/run1"):
            return httpx.Response(
                200, json={"data": {"id": "run1", "status": "SUCCEEDED"}}
            )
        if request.url.path.endswith("/datasets/dataset1/items"):
            return httpx.Response(
                200, json=[{"url": "https://example.com", "title": "Example"}]
            )
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ApifyToolProvider(
            token="token", base_url="https://api.test/v2", client=client
        )
        status = await provider.job_status("run1")
        assert status["status"] == "SUCCEEDED"
        page = await provider.result_page("dataset1", offset=0, limit=5)
        assert page["items"][0]["title"] == "Example"


@pytest.mark.asyncio
async def test_composio_search_describe_and_execute() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "key"
        if request.method == "GET" and request.url.path.endswith("/tools"):
            assert request.url.params["query"] == "github"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "slug": "GITHUB_CREATE_ISSUE",
                            "name": "Create issue",
                            "description": "Create a repository issue",
                            "toolkit": {"slug": "github", "name": "GitHub"},
                            "input_parameters": {"title": {"type": "string"}},
                            "output_parameters": {"html_url": {"type": "string"}},
                            "no_auth": False,
                            "tags": ["github"],
                        }
                    ]
                },
            )
        if request.method == "GET" and request.url.path.endswith(
            "/tools/GITHUB_CREATE_ISSUE"
        ):
            return httpx.Response(
                200,
                json={
                    "slug": "GITHUB_CREATE_ISSUE",
                    "name": "Create issue",
                    "description": "Create a repository issue",
                    "toolkit": {"slug": "github", "name": "GitHub"},
                    "input_parameters": {"title": {"type": "string"}},
                    "no_auth": False,
                },
            )
        if request.method == "POST" and request.url.path.endswith(
            "/tools/execute/GITHUB_CREATE_ISSUE"
        ):
            body = json.loads(request.content)
            assert body["connected_account_id"] == "ca_work"
            assert body["arguments"] == {"title": "Test"}
            return httpx.Response(
                200,
                json={
                    "successful": True,
                    "data": {"html_url": "https://github.com/o/r/issues/1"},
                    "log_id": "log1",
                },
            )
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ComposioToolProvider(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
        )
        tools = await provider.search("github", limit=3)
        assert tools[0].ref == "composio:GITHUB_CREATE_ISSUE"
        assert tools[0].side_effecting is True
        described = await provider.describe("GITHUB_CREATE_ISSUE")
        assert described.requires_auth is True
        result = await provider.execute(
            "GITHUB_CREATE_ISSUE",
            {"title": "Test"},
            account="ca_work",
        )
        assert result["status"] == "completed"
        assert result["data"]["html_url"].endswith("/1")
