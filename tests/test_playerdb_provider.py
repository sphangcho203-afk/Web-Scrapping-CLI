from __future__ import annotations

import httpx
import pytest

from internet_hands.playerdb_provider import PlayerDbProvider


@pytest.mark.asyncio
async def test_playerdb_cross_platform_lookup_is_bounded_and_identified() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/player/xbox/Some%20Gamer"
        assert request.headers["user-agent"].startswith("OpenCrawl/")
        return httpx.Response(
            200,
            json={
                "code": "player.found",
                "data": {"player": {"username": "Some Gamer", "id": "xuid-1"}},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = PlayerDbProvider(client=client, validate_urls=False)
        result = await provider.execute("xbox", {"id": "Some Gamer"})

    assert result["status"] == "completed"
    assert result["metadata"]["platform"] == "xbox"
    assert result["data"]["data"]["player"]["id"] == "xuid-1"


@pytest.mark.asyncio
async def test_playerdb_exposes_four_identity_platforms() -> None:
    provider = PlayerDbProvider(validate_urls=False)
    status = await provider.status()
    assert set(status["platforms"]) == {"minecraft", "steam", "xbox", "hytale"}
    assert status["authentication"] == "none"
    refs = {tool.ref for tool in await provider.search("identity", limit=20)}
    assert {
        "playerdb:minecraft",
        "playerdb:steam",
        "playerdb:xbox",
        "playerdb:hytale",
    }.issubset(refs)


@pytest.mark.asyncio
async def test_playerdb_reports_rate_limit_without_retry_storm() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "10"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = PlayerDbProvider(client=client, validate_urls=False)
        with pytest.raises(RuntimeError, match="retry after 10s"):
            await provider.execute("minecraft", {"id": "Player"})
