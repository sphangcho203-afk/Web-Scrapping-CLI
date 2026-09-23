from __future__ import annotations

import json

import httpx
import pytest

from internet_hands.composio_bridge import ComposioBridgeProvider


def _tool(slug: str, toolkit: str = "github") -> dict:
    return {
        "slug": slug,
        "name": slug.replace("_", " ").title(),
        "description": "test tool",
        "toolkit": {"slug": toolkit, "name": toolkit.title()},
        "input_parameters": {"type": "object", "properties": {}},
        "output_parameters": {"type": "object"},
        "no_auth": False,
        "tags": [toolkit],
    }


def _connection(account_id: str, toolkit: str, alias: str) -> dict:
    return {
        "id": account_id,
        "status": "ACTIVE",
        "alias": alias,
        "toolkit": {"slug": toolkit},
    }


@pytest.mark.asyncio
async def test_connected_only_filters_unconnected_toolkits() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/connected_accounts"):
            return httpx.Response(200, json={"items": [_connection("ca_github", "github", "work")]})
        if request.url.path.endswith("/tools"):
            return httpx.Response(
                200,
                json={"items": [_tool("GITHUB_GET_REPO"), _tool("SLACK_SEND_MESSAGE", "slack")]},
            )
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ComposioBridgeProvider(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
            connected_only=True,
        )
        tools = await provider.search("anything", limit=10)
        assert [tool.ref for tool in tools] == ["composio:GITHUB_GET_REPO"]
        assert tools[0].metadata["connected"] is True
        assert tools[0].metadata["configured"] is False
        assert tools[0].metadata["account_routing"] == "locked"
        assert "connected_account_aliases" not in tools[0].metadata


@pytest.mark.asyncio
async def test_execution_is_locked_without_account_policy() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/connected_accounts"):
            return httpx.Response(200, json={"items": [_connection("ca_github", "github", "work")]})
        if request.url.path.endswith("/tools/GITHUB_CREATE_ISSUE"):
            return httpx.Response(200, json=_tool("GITHUB_CREATE_ISSUE"))
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ComposioBridgeProvider(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
            connected_only=True,
            allow_project_accounts=False,
            allowed_accounts=set(),
        )
        with pytest.raises(PermissionError, match="routing is locked"):
            await provider.execute("GITHUB_CREATE_ISSUE", {"title": "x"})


@pytest.mark.asyncio
async def test_allowlisted_connection_is_reported_configured() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/connected_accounts"):
            return httpx.Response(
                200,
                json={"items": [_connection("ca_work", "github", "work")]},
            )
        if request.url.path.endswith("/tools/GITHUB_CREATE_ISSUE"):
            return httpx.Response(200, json=_tool("GITHUB_CREATE_ISSUE"))
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ComposioBridgeProvider(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
            allowed_accounts={"work"},
        )
        descriptor = await provider.describe("GITHUB_CREATE_ISSUE")
        assert descriptor.metadata["connected"] is True
        assert descriptor.metadata["configured"] is True
        assert descriptor.metadata["account_routing"] == "configured"


@pytest.mark.asyncio
async def test_allowlisted_alias_routes_to_matching_connected_account() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/connected_accounts"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        _connection("ca_personal", "github", "personal"),
                        _connection("ca_work", "github", "work"),
                    ]
                },
            )
        if request.method == "GET" and request.url.path.endswith("/tools/GITHUB_CREATE_ISSUE"):
            return httpx.Response(200, json=_tool("GITHUB_CREATE_ISSUE"))
        if request.method == "POST" and request.url.path.endswith("/tools/execute/GITHUB_CREATE_ISSUE"):
            seen.update(json.loads(request.content))
            return httpx.Response(200, json={"successful": True, "data": {"ok": True}})
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ComposioBridgeProvider(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
            allowed_accounts={"work"},
        )
        result = await provider.execute("GITHUB_CREATE_ISSUE", {"title": "x"})
        assert result["status"] == "completed"
        assert seen["connected_account_id"] == "ca_work"


@pytest.mark.asyncio
async def test_multiple_allowed_accounts_require_explicit_selection() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/connected_accounts"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        _connection("ca_one", "github", "one"),
                        _connection("ca_two", "github", "two"),
                    ]
                },
            )
        if request.url.path.endswith("/tools/GITHUB_CREATE_ISSUE"):
            return httpx.Response(200, json=_tool("GITHUB_CREATE_ISSUE"))
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ComposioBridgeProvider(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
            allowed_accounts={"one", "two"},
        )
        with pytest.raises(PermissionError, match="multiple allowed"):
            await provider.execute("GITHUB_CREATE_ISSUE", {"title": "x"})


@pytest.mark.asyncio
async def test_explicit_blocked_account_cannot_bypass_allowlist() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/connected_accounts"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        _connection("ca_personal", "github", "personal"),
                        _connection("ca_work", "github", "work"),
                    ]
                },
            )
        if request.url.path.endswith("/tools/GITHUB_CREATE_ISSUE"):
            return httpx.Response(200, json=_tool("GITHUB_CREATE_ISSUE"))
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ComposioBridgeProvider(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
            allowed_accounts={"work"},
        )
        with pytest.raises(PermissionError, match="blocked by bridge policy"):
            await provider.execute(
                "GITHUB_CREATE_ISSUE",
                {"title": "x"},
                account="personal",
            )


@pytest.mark.asyncio
async def test_status_is_sanitized_by_default() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/connected_accounts"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        _connection("secret-account-id", "github", "private-alias"),
                        _connection("mail-id", "gmail", "avenix"),
                    ]
                },
            )
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ComposioBridgeProvider(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
        )
        status = await provider.status()
        encoded = json.dumps(status)
        assert "secret-account-id" not in encoded
        assert "private-alias" not in encoded
        assert status["account_routing"] == "locked"
        assert status["connected_toolkits"] == [
            {"toolkit": "github", "accounts": 1},
            {"toolkit": "gmail", "accounts": 1},
        ]
