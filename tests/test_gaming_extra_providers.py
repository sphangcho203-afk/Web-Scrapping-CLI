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



@pytest.mark.asyncio
async def test_steam_game_agnostic_stats_and_achievements_routes() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        assert request.url.params["key"] == "steam-secret"
        assert request.url.params["steamid"] == "76561198000000000"
        assert request.url.params["appid"] == "730"
        if "GetPlayerAchievements" in request.url.path:
            return httpx.Response(200, json={"playerstats": {"achievements": [{"apiname": "WIN_ONE"}]}})
        return httpx.Response(200, json={"playerstats": {"stats": [{"name": "kills", "value": 10}]}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = SteamGamingProvider(
            api_key="steam-secret", client=client, validate_urls=False
        )
        achievements = await provider.execute(
            "player-achievements",
            {"steamid": "76561198000000000", "appid": 730},
        )
        stats = await provider.execute(
            "user-stats",
            {"steamid": "76561198000000000", "appid": 730},
        )

    assert achievements["data"]["playerstats"]["achievements"][0]["apiname"] == "WIN_ONE"
    assert stats["data"]["playerstats"]["stats"][0]["value"] == 10
    assert any("GetPlayerAchievements" in path for path in seen)
    assert any("GetUserStatsForGame" in path for path in seen)


@pytest.mark.asyncio
async def test_steam_level_and_badges_share_server_side_identity_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["key"] == "steam-secret"
        assert request.url.params["steamid"] == "76561198000000000"
        if "GetSteamLevel" in request.url.path:
            return httpx.Response(200, json={"response": {"player_level": 42}})
        return httpx.Response(200, json={"response": {"badges": [{"badgeid": 1}], "player_xp": 9000}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = SteamGamingProvider(
            api_key="steam-secret", client=client, validate_urls=False
        )
        level = await provider.execute("player-level", {"steamid": "76561198000000000"})
        badges = await provider.execute("badges", {"steamid": "76561198000000000"})

    assert level["data"]["response"]["player_level"] == 42
    assert badges["data"]["response"]["player_xp"] == 9000
