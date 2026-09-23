from __future__ import annotations

import asyncio

import pytest
import httpx

from internet_hands.capability_economics import estimate_call, settle_measured_cost
from internet_hands.game_core_provider import GameCoreProvider
from internet_hands.gaming_capabilities import build_gaming_capabilities


def test_bundled_mlbb_data_has_provenance_and_is_not_presented_as_live() -> None:
    provider = GameCoreProvider()
    detail = asyncio.run(provider.execute("mlbb-hero", {"hero": "Lancelot"}))["data"]
    assert detail["hero"]["name"] == "Lancelot"
    assert "jungle" in detail["hero"]["lanes"]
    assert detail["provenance"]["license"] == "MIT"
    assert detail["provenance"]["current_patch"] is False
    assert detail["provenance"]["hero_revision"] == "20251226"
    heroes = asyncio.run(provider.execute("mlbb-heroes", {"query": "jungle", "limit": 5}))["data"]
    assert heroes["total"] >= 5
    assert len(heroes["results"]) == 5
    items = asyncio.run(provider.execute("mlbb-items", {"query": "Blade of Despair"}))["data"]
    assert items["results"][0]["name"] == "Blade of Despair"
    with pytest.raises(ValueError, match="historical snapshot"):
        asyncio.run(provider.execute("mlbb-hero", {"hero": "invented hero"}))


def test_keyless_match_analysis_calculates_real_sample_and_rejects_malformed_results() -> None:
    provider = GameCoreProvider()
    result = asyncio.run(provider.execute("match-analysis", {"game": "Dota 2", "matches": [
        {"win": True, "hero": "Puck", "kills": 8, "deaths": 2, "assists": 6},
        {"win": False, "hero": "Puck", "kills": 2, "deaths": 4, "assists": 4},
        {"win": True, "hero": "Axe", "kills": 5, "deaths": 0, "assists": 7},
    ]}))["data"]
    assert result["overall"]["win_rate"] == 66.7
    assert result["overall"]["kda"] == 5.33
    assert result["current_streak"] == {"outcome": "win", "games": 1}
    assert result["heroes"][0]["hero"] == "Puck"
    for invalid in ([{"win": 1}], [{"win": True, "kills": -1}], []):
        with pytest.raises(ValueError):
            asyncio.run(provider.execute("match-analysis", {"game": "Dota 2", "matches": invalid}))


def test_local_capability_is_game_agnostic_and_failed_run_releases_credit() -> None:
    caps = build_gaming_capabilities()
    assert any(cap.id == "game.matches.analyze" and cap.pack == "gaming-common" for cap in caps)
    quote = estimate_call("gamecore:match-analysis", {}, "free")
    assert quote.credits == 1
    assert settle_measured_cost("gamecore:match-analysis", {}, "free",
                                reserved_credits=quote.credits, execution_usage={"completed": False}) == 0


def test_riot_reference_pins_published_version_and_needs_no_api_key() -> None:
    paths: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "ddragon.leagueoflegends.com"
        paths.append(request.url.path)
        if request.url.path == "/api/versions.json":
            return httpx.Response(200, json=["16.18.1"])
        if request.url.path.endswith("/champion.json"):
            return httpx.Response(200, json={"data": {
                "Ahri": {"name": "Ahri", "tags": ["Mage"], "title": "the Nine-Tailed Fox"},
                "Aatrox": {"name": "Aatrox", "tags": ["Fighter"]},
            }})
        return httpx.Response(200, json={"data": {
            "1001": {"name": "Boots", "gold": {"total": 300}, "stats": {"FlatMovementSpeedMod": 25}},
        }})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = GameCoreProvider(client)
            heroes = (await provider.execute("league-champions", {"query": "mage"}))["data"]
            items = (await provider.execute("league-items", {"query": "boots"}))["data"]
            assert heroes["results"] == [{"id": "Ahri", "name": "Ahri",
                                           "title": "the Nine-Tailed Fox", "roles": ["Mage"]}]
            assert items["results"][0]["cost"] == 300
            assert heroes["provenance"]["version"] == "16.18.1"
            assert paths.count("/api/versions.json") == 1
            assert paths[1] == "/cdn/16.18.1/data/en_US/champion.json"

    asyncio.run(run())
