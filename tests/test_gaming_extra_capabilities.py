from __future__ import annotations

from internet_hands.gaming_extra_capabilities import build_extra_gaming_capabilities
from internet_hands.gaming_profiles import build_gaming_profile_plan


def test_extra_gaming_capabilities_cover_official_sources() -> None:
    capabilities = build_extra_gaming_capabilities()
    ids = {capability.id for capability in capabilities}
    assert {
        "steam.player.resolve",
        "steam.player.profile",
        "steam.games.recent",
        "steam.games.owned",
        "riot.account.lookup",
        "league.player.profile",
        "league.rank.current",
        "league.champion.mastery",
        "league.matches.recent",
        "tft.matches.recent",
    }.issubset(ids)
    assert all(capability.read_only for capability in capabilities)
    assert all("gaming" in capability.tags for capability in capabilities)


def test_league_profile_plan_uses_puuid_intelligence_bundle() -> None:
    plan = build_gaming_profile_plan(
        "lol",
        {"puuid": "P1", "platform": "sg2", "regional": "asia"},
    )
    capabilities = [request["capability"] for request in plan.requests]
    assert capabilities == [
        "league.player.profile",
        "league.rank.current",
        "league.champion.mastery",
        "league.matches.recent",
    ]


def test_steam_profile_plan_uses_public_profile_and_playtime() -> None:
    plan = build_gaming_profile_plan("steam", {"steamid": "76561198000000000"})
    capabilities = [request["capability"] for request in plan.requests]
    assert capabilities == [
        "steam.player.profile",
        "steam.games.recent",
        "steam.games.owned",
    ]
    assert plan.requests[0]["arguments"]["steamids"] == "76561198000000000"


def test_tft_riot_id_plan_resolves_puuid_first() -> None:
    plan = build_gaming_profile_plan(
        "tft",
        {"game_name": "Player", "tag_line": "TAG", "regional": "asia"},
    )
    assert [request["capability"] for request in plan.requests] == [
        "riot.account.lookup"
    ]
    assert "PUUID" in plan.note
