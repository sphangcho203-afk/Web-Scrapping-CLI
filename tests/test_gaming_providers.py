from __future__ import annotations

import json

import httpx
import pytest

from internet_hands.gaming_providers import (
    build_brawlstars_provider,
    build_gaming_providers,
    build_opendota_provider,
    build_roblox_provider,
    build_valorant_provider,
)


def test_gaming_provider_names_are_unique() -> None:
    providers = build_gaming_providers()
    names = [provider.name for provider in providers]
    assert len(names) == len(set(names))
    assert {
        "opendota",
        "valorant",
        "enka",
        "mojang",
        "hypixel",
        "roblox",
        "osu",
        "brawlstars",
        "clashofclans",
        "clashroyale",
    }.issubset(names)


@pytest.mark.asyncio
async def test_opendota_player_heroes_is_read_only() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/players/123/heroes"
        return httpx.Response(200, json=[{"hero_id": 1, "games": 50, "win": 31}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = build_opendota_provider()
        provider.client = client
        provider.validate_urls = False
        result = await provider.execute("player-heroes", {"account_id": "123"})

    assert result["status"] == "completed"
    assert result["data"][0]["games"] == 50
    descriptor = await provider.describe("player-heroes")
    assert descriptor.side_effecting is False


@pytest.mark.asyncio
async def test_valorant_provider_uses_server_side_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HENRIKDEV_API_KEY", "server-secret")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["authorization"] == "server-secret"
        assert request.url.path == "/valorant/v2/mmr/ap/Test Name/TAG"
        assert b"Test%20Name" in request.url.raw_path
        return httpx.Response(200, json={"status": 200, "data": {"currenttierpatched": "Gold 3"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = build_valorant_provider()
        provider.client = client
        provider.validate_urls = False
        descriptor = await provider.describe("mmr")
        serialized = json.dumps(descriptor.to_dict())
        assert "server-secret" not in serialized
        result = await provider.execute(
            "mmr",
            {"version": "v2", "region": "ap", "name": "Test Name", "tag": "TAG"},
        )

    assert result["status"] == "completed"
    assert result["data"]["data"]["currenttierpatched"] == "Gold 3"


@pytest.mark.asyncio
async def test_supercell_player_tag_is_url_encoded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAWL_STARS_AUTHORIZATION", "Bearer token")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["authorization"] == "Bearer token"
        assert b"%23ABC123" in request.url.raw_path
        return httpx.Response(200, json={"tag": "#ABC123", "name": "Player"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = build_brawlstars_provider()
        provider.client = client
        provider.validate_urls = False
        result = await provider.execute("player", {"player_tag": "#ABC123"})

    assert result["data"]["tag"] == "#ABC123"



@pytest.mark.asyncio
async def test_roblox_public_profile_expansion_uses_read_only_endpoints() -> None:
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        assert request.method == "GET"
        if request.url.path.endswith("/username-history"):
            return httpx.Response(200, json={"data": [{"name": "OldName"}]})
        if request.url.path.endswith("/currently-wearing"):
            return httpx.Response(200, json={"assetIds": [1, 2, 3]})
        if request.url.path.endswith("/groups/roles"):
            return httpx.Response(200, json={"data": [{"group": {"id": 1}, "role": {"name": "Member"}}]})
        if request.url.path.endswith("/games"):
            return httpx.Response(200, json={"data": [{"id": 42, "name": "Public Game"}]})
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = build_roblox_provider()
        provider.client = client
        provider.validate_urls = False
        history = await provider.execute("username-history", {"user_id": 123, "limit": 10})
        wearing = await provider.execute("currently-wearing", {"user_id": 123})
        groups = await provider.execute("group-roles", {"user_id": 123})
        games = await provider.execute("created-games", {"user_id": 123, "limit": 10})

    assert history["data"]["data"][0]["name"] == "OldName"
    assert wearing["data"]["assetIds"] == [1, 2, 3]
    assert groups["data"]["data"][0]["role"]["name"] == "Member"
    assert games["data"]["data"][0]["name"] == "Public Game"
    assert all(path.startswith("/v1/") or path.startswith("/v2/") for path in requests)


@pytest.mark.asyncio
async def test_roblox_expanded_tools_remain_read_only() -> None:
    provider = build_roblox_provider()
    expected = {
        "username-history",
        "avatar",
        "currently-wearing",
        "created-games",
        "group-roles",
        "primary-group",
    }
    descriptors = {tool.tool_id: tool for tool in await provider.search("", limit=50)}
    assert expected.issubset(descriptors)
    assert all(descriptors[tool_id].side_effecting is False for tool_id in expected)
