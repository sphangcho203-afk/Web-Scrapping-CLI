from __future__ import annotations

from internet_hands.gaming_capabilities import build_gaming_capabilities


def test_gaming_capability_catalog_has_core_games() -> None:
    capabilities = build_gaming_capabilities()
    ids = {capability.id for capability in capabilities}
    expected = {
        "mlbb.rank.current",
        "mlbb.hero.history",
        "valorant.account.lookup",
        "valorant.rank.mmr",
        "valorant.matches.recent",
        "dota2.player.profile",
        "dota2.hero.most_used",
        "minecraft.ign.resolve",
        "hypixel.player.profile",
        "genshin.player.showcase",
        "hsr.player.showcase",
        "zzz.player.showcase",
        "roblox.player.search",
        "osu.player.profile",
        "brawlstars.player.profile",
        "clashofclans.player.profile",
        "clashroyale.player.profile",
    }
    assert expected.issubset(ids)


def test_gaming_capabilities_are_read_only_and_tagged() -> None:
    for capability in build_gaming_capabilities():
        assert capability.read_only is True
        assert "gaming" in capability.tags
        assert capability.candidates


def test_valorant_and_osu_defaults_are_resolved_server_side() -> None:
    by_id = {capability.id: capability for capability in build_gaming_capabilities()}
    valorant = by_id["valorant.rank.mmr"]
    assert valorant.candidates[0].defaults["version"] == "v2"
    osu_best = by_id["osu.scores.best"]
    assert osu_best.candidates[0].defaults["type"] == "best"
