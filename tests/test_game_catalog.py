from __future__ import annotations

from types import SimpleNamespace

from internet_hands.game_catalog import build_game_adapters


def test_game_catalog_only_lists_registered_capabilities_and_live_provider_state() -> None:
    candidates = (SimpleNamespace(provider="riot", ref="riot:lol-ranked-entries"),)
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


def test_mixed_provider_does_not_mark_credential_locked_tool_ready() -> None:
    status = {"executable": True, "tool_availability": {"sample:open": True, "sample:locked": False}}
    adapter = build_game_adapters({
        "league.test": SimpleNamespace(
            id="league.test", name="Locked", description="", pack="league",
            candidates=(SimpleNamespace(provider="sample", ref="sample:locked"),), input_schema={}),
    })["league"]
    result = adapter.to_dict({"sample": status}, details=True)
    assert result["provider_ready_count"] == 0
    assert result["capabilities"][0]["availability"] == "key_required"


def test_dynamic_catalog_lookup_is_not_counted_as_a_runnable_tool() -> None:
    adapter = build_game_adapters({"mlbb.discovery": SimpleNamespace(
        id="mlbb.discovery", name="Discover", description="", pack="mlbb",
        candidates=(SimpleNamespace(provider="openapi", ref=None, search="MLBB rank"),), input_schema={},
    )})["mlbb"]
    result = adapter.to_dict({"openapi": {"searchable": True, "executable": True}}, details=True)
    assert result["provider_ready_count"] == 0
    assert result["capabilities"][0]["availability"] == "discovery_required"
