from __future__ import annotations

from types import SimpleNamespace

from internet_hands.game_catalog import build_game_adapters


def test_game_catalog_only_lists_registered_capabilities_and_live_provider_state() -> None:
    candidates = (SimpleNamespace(provider="riot"),)
    capabilities = {
        "league.rank.current": SimpleNamespace(
            id="league.rank.current", name="League rank", description="Ranked data",
            pack="league", candidates=candidates, input_schema={},
        ),
        "unrelated": SimpleNamespace(
            id="unrelated", name="Web", description="Web search", pack="web",
            candidates=(), input_schema={},
        ),
    }
    adapters = build_game_adapters(capabilities)
    assert list(adapters) == ["league"]
    unavailable = adapters["league"].to_dict({"riot": {"executable": False}}, details=True)
    assert unavailable["provider_ready_count"] == 0
    assert unavailable["capabilities"][0]["provider_ready"] is False
    ready = adapters["league"].to_dict({"riot": {"executable": True}})
    assert ready["provider_ready_count"] == 1
    assert "capabilities" not in ready
