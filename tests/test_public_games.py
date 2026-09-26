import json

import pytest
from test_public_data_provider import fetched

from internet_hands import public_game_provider as module
from internet_hands.capability_economics import estimate_call, settle_measured_cost
from internet_hands.execution_meter import (
    execution_usage_snapshot,
    reset_execution_meter,
    start_execution_meter,
)
from internet_hands.game_catalog import build_game_adapters
from internet_hands.game_execution import discover_game_tools
from internet_hands.public_game_manifest import PUBLIC_GAMES
from internet_hands.tool_mesh import ToolMesh


async def test_over_100_games_have_specific_discoverable_callable_operations():
    caps = module.build_public_game_capabilities()
    catalog = build_game_adapters({cap.id: cap for cap in caps})
    assert len(PUBLIC_GAMES) >= 100 and len(catalog) == len(PUBLIC_GAMES)
    assert len({cap.id for cap in caps}) == len(caps) == 3 * len(PUBLIC_GAMES)
    mesh = ToolMesh([module.PublicGameProvider()])
    for cap in caps:
        options = await discover_game_tools(cap, mesh)
        assert len(options["tools"]) == 1
        assert options["tools"][0]["ref"] == cap.candidates[0].ref
        assert not options["tools"][0]["side_effecting"]
        assert not any(word in cap.id for word in ("profile", "match", "rank"))


async def test_activity_zero_is_valid_and_cache_does_not_refetch_or_rebill(monkeypatch):
    requests = []
    async def fetch(url, **kwargs):
        requests.append(url)
        return fetched(json.dumps({"response": {"result": 1, "player_count": 0}}), "application/json", url)
    monkeypatch.setattr(module, "fetch_url", fetch)
    mesh = ToolMesh([module.PublicGameProvider()])
    call = {"ref": "gamepublic:730/activity", "arguments": {}}
    quote = estimate_call("mesh_execute", call, "free")
    charges = []
    for cached in (False, True):
        token = start_execution_meter()
        try:
            result = await mesh.execute(call["ref"], {})
            usage = execution_usage_snapshot()
        finally:
            reset_execution_meter(token)
        assert result["status"] == "completed"
        assert result["data"]["current_players"] == 0
        assert result["data"]["cached"] is cached
        assert result["data"]["platform_scope"] == "Steam"
        charges.append(settle_measured_cost("mesh_execute", call, "free", reserved_credits=quote.credits, execution_usage=usage))
        result["data"]["current_players"] = 999  # caller cannot mutate cached results
    assert len(requests) == 1 and charges == [5, 2]
    assert "key=" not in requests[0]


@pytest.mark.parametrize(("operation", "payload", "status"), [
    ("news", {"appnews": {"appid": 730, "newsitems": []}}, "completed"),
    ("news", {"appnews": {"appid": 570, "newsitems": []}}, "failed"),
    ("activity", {"response": {"result": 42, "player_count": 0}}, "failed"),
    ("activity", {"response": {"result": 1, "player_count": True}}, "failed"),
    ("achievements", {"achievementpercentages": {"achievements": []}}, "completed"),
    ("achievements", {}, "failed"),
])
async def test_missing_data_never_becomes_fake_telemetry(monkeypatch, operation, payload, status):
    async def fetch(url, **kwargs):
        return fetched(json.dumps(payload), "application/json", url)
    monkeypatch.setattr(module, "fetch_url", fetch)
    result = await ToolMesh([module.PublicGameProvider()]).execute(f"gamepublic:730/{operation}", {})
    assert result["status"] == status
    if status == "completed":
        assert result["data"]["empty"] is True


@pytest.mark.parametrize("status", [403, 404, 429, 500])
async def test_upstream_failures_are_not_cached(monkeypatch, status):
    requests = []
    async def fetch(url, **kwargs):
        requests.append(url)
        return fetched("denied", "text/plain", url, status)
    monkeypatch.setattr(module, "fetch_url", fetch)
    mesh = ToolMesh([module.PublicGameProvider()])
    for _ in range(2):
        result = await mesh.execute("gamepublic:730/activity", {})
        assert result["status"] == "failed" and str(status) in result["error"]
    assert len(requests) == 2


async def test_invalid_ids_and_arguments_do_not_make_requests(monkeypatch):
    async def never(*args, **kwargs):
        pytest.fail("Invalid operation reached network")
    monkeypatch.setattr(module, "fetch_url", never)
    provider = module.PublicGameProvider()
    for tool_id, args in [("0/news", {}), ("730/../../secret", {}), ("730/news", {"count": 500}),
                          ("730/activity", {"appid": 570}), ("730/news", {"url": "http://localhost"})]:
        with pytest.raises(ValueError):
            await provider.execute(tool_id, args)
