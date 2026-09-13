from __future__ import annotations

import pytest

from internet_hands.gaming_profiles import build_gaming_profile_plan


def test_mlbb_profile_fetches_rich_payload_once() -> None:
    plan = build_gaming_profile_plan("mlbb", {"id": "123", "zone": "456"})
    assert plan.game == "mlbb"
    assert [row["capability"] for row in plan.requests] == ["mlbb.player.lookup"]


def test_valorant_profile_bundles_rank_matches_and_history() -> None:
    plan = build_gaming_profile_plan(
        "valorant",
        {"name": "Player", "tag": "TAG", "region": "ap"},
    )
    assert [row["capability"] for row in plan.requests] == [
        "valorant.account.lookup",
        "valorant.rank.mmr",
        "valorant.matches.recent",
        "valorant.rank.history",
    ]


def test_dota_profile_has_mains_and_recent_form() -> None:
    plan = build_gaming_profile_plan("dota2", {"account_id": "123"})
    capabilities = {row["capability"] for row in plan.requests}
    assert "dota2.player.profile" in capabilities
    assert "dota2.hero.most_used" in capabilities
    assert "dota2.stats.winloss" in capabilities
    assert "dota2.matches.recent" in capabilities
    assert "dota2.mmr.history" in capabilities


def test_minecraft_name_resolution_is_dependency_aware() -> None:
    plan = build_gaming_profile_plan("minecraft", {"username": "Notch"})
    assert plan.requests[0]["capability"] == "minecraft.ign.resolve"
    assert "UUID" in plan.note


def test_profile_plan_rejects_missing_identity_fields() -> None:
    with pytest.raises(ValueError, match="region"):
        build_gaming_profile_plan("valorant", {"name": "Player", "tag": "TAG"})
