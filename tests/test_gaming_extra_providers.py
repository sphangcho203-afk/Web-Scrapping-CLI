from __future__ import annotations

import json

import httpx
import pytest

from internet_hands.gaming_extra_providers import RiotGamingProvider, SteamGamingProvider


@pytest.mark.asyncio
async def test_steam_key_stays_server_side() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/ISteamUser/GetPlayerSummaries/v2/")
        assert request.url.params["key"] == "steam-secret"
        assert request.url.params["steamids"] == "76561198000000000"
        return httpx.Response(
            200,
            json={"response": {"players": [{"steamid": "76561198000000000"}]}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = SteamGamingProvider(
            api_key="steam-secret", client=client, validate_urls=False
        )
        descriptor = await provider.describe("player-summaries")
        assert "steam-secret" not in json.dumps(descriptor.to_dict())
        result = await provider.execute(
            "player-summaries", {"steamids": "76561198000000000"}
        )

    assert result["status"] == "completed"
    assert result["data"]["response"]["players"][0]["steamid"]


@pytest.mark.asyncio
async def test_riot_key_and_platform_route_are_server_side() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "sg2.api.riotgames.com"
        assert request.headers["x-riot-token"] == "riot-secret"
        assert request.url.path.endswith("/lol/league/v4/entries/by-puuid/PUUID123")
        return httpx.Response(200, json=[{"tier": "GOLD", "rank": "I"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RiotGamingProvider(
            api_key="riot-secret", client=client, validate_urls=False
        )
        descriptor = await provider.describe("lol-ranked-entries")
        assert "riot-secret" not in json.dumps(descriptor.to_dict())
        result = await provider.execute(
            "lol-ranked-entries",
            {"platform": "sg2", "puuid": "PUUID123"},
        )

    assert result["data"][0]["tier"] == "GOLD"


@pytest.mark.asyncio
async def test_riot_rejects_arbitrary_routing_hosts() -> None:
    provider = RiotGamingProvider(api_key="riot-secret", validate_urls=False)
    with pytest.raises(ValueError, match="platform routing"):
        await provider.execute(
            "lol-ranked-entries",
            {"platform": "evil.example.com", "puuid": "PUUID123"},
        )


@pytest.mark.asyncio
async def test_riot_id_is_url_encoded() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "asia.api.riotgames.com"
        assert b"Some%20Name" in request.url.raw_path
        assert request.headers["x-riot-token"] == "riot-secret"
        return httpx.Response(200, json={"puuid": "P1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RiotGamingProvider(
            api_key="riot-secret", client=client, validate_urls=False
        )
        result = await provider.execute(
            "account-by-riot-id",
            {"regional": "asia", "game_name": "Some Name", "tag_line": "TAG"},
        )

    assert result["data"]["puuid"] == "P1"
