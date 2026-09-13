from __future__ import annotations

import json

import httpx
import pytest

from internet_hands.gaming_providers import (
    build_brawlstars_provider,
    build_gaming_providers,
    build_opendota_provider,
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
        assert request.url.path == "/valorant/v2/mmr/ap/Test%20Name/TAG"
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
