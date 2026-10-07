from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from starlette.responses import JSONResponse

from internet_hands.auth import current_auth
from internet_hands.capability_availability import REASONS
from internet_hands.capability_packs import Capability, CapabilityCandidate, CapabilityRegistry
from internet_hands.control_store import AuthIdentity, ControlError
from internet_hands.game_execution import discover_game_tools
from internet_hands.mcp_gateway import MCPGatewayASGI
from internet_hands.tool_mesh import ToolDescriptor, ToolMesh


class SetupProvider:
    name = "setup"

    def __init__(self, *, configured=True, tool_ready=True, side_effecting=False, error=None):
        self.configured = configured
        self.tool_ready = tool_ready
        self.side_effecting = side_effecting
        self.error = error
        self.inspected_users = []
        self.inspected_tools = []

    async def status(self):
        return {"searchable": True, "executable": self.configured,
                "tool_availability": {"setup:tool": self.tool_ready}}

    async def describe(self, tool_id):
        identity = current_auth.get()
        self.inspected_users.append(identity.user_id if identity else None)
        self.inspected_tools.append(tool_id)
        if self.error:
            raise self.error
        return ToolDescriptor("setup:" + tool_id, "setup", tool_id, "Setup operation",
                              side_effecting=self.side_effecting,
                              metadata={"method": "GET", "configured": self.configured})

    async def execute(self, *args, **kwargs):
        raise AssertionError("Availability checks must never execute an operation")


def registry(provider, *, read_only=True, candidates=None):
    cap = Capability("game.setup", "Setup", "", "game", ("gaming",),
                     tuple(candidates or [CapabilityCandidate("setup", ref="setup:tool")]),
                     read_only=read_only)
    return CapabilityRegistry(ToolMesh([provider]), [cap])


@pytest.mark.parametrize("options,code", [
    ({"configured": False}, "not_configured"),
    ({"tool_ready": False}, "not_configured"),
    ({"side_effecting": True}, "read_only_mismatch"),
    ({"error": PermissionError("private-account-id")}, "connection_required"),
    ({"error": TimeoutError("private-url")}, "timeout"),
    ({"error": RuntimeError("private-url")}, "temporarily_unavailable"),
])
async def test_resolve_has_safe_actionable_reason(options, code):
    result = await registry(SetupProvider(**options)).resolve("game.setup")
    row = result["resolved"][0]
    assert row["available"] is False
    assert row["reason_code"] == code
    assert row["reason"] == REASONS[code]
    assert "private-" not in json.dumps(result)


async def test_http_404_does_not_expose_upstream_url_or_token():
    request = httpx.Request("GET", "https://private.example/tools/key?api_key=secret")
    response = httpx.Response(404, request=request)
    error = httpx.HTTPStatusError("private response secret", request=request, response=response)
    provider = SetupProvider(error=error)
    reg = registry(provider)
    row = (await reg.resolve("game.setup"))["resolved"][0]
    assert row["reason_code"] == "tool_not_found"
    assert "secret" not in json.dumps(row)
    tools = await discover_game_tools(reg.capabilities["game.setup"], reg.mesh)
    assert tools == {"tools": [], "reasons": [REASONS["tool_not_found"]]}


async def test_preflight_matches_arguments_and_preserves_preview():
    provider = SetupProvider(tool_ready=False)
    candidates = [CapabilityCandidate("setup", ref="setup:tool", when={"mode": "blocked"}),
                  CapabilityCandidate("setup", ref="setup:ready", when={"mode": "ready"})]
    reg = registry(provider, candidates=candidates)
    with pytest.raises(ControlError, match="server-side credentials"):
        await reg.preflight("game.setup", {"mode": "blocked"})
    assert provider.inspected_tools == ["tool"]
    await reg.preflight("game.setup", {"mode": "ready"})
    await reg.preflight("game.setup", {"mode": "blocked"}, dry_run=True)
    with pytest.raises(ControlError, match="matches these arguments"):
        await reg.preflight("game.setup", {"mode": "other"})


async def test_write_preflight_requires_explicit_consent():
    provider = SetupProvider(side_effecting=True)
    reg = registry(provider, read_only=False)
    with pytest.raises(ControlError, match="allow_side_effects"):
        await reg.preflight("game.setup", {})
    assert provider.inspected_tools == []
    await reg.preflight("game.setup", {}, dry_run=True)
    await reg.preflight("game.setup", {}, allow_side_effects=True)


async def test_ads_actor_requires_consent_and_reports_real_configuration():
    from internet_hands.capability_packs import build_default_capabilities
    from internet_hands.tool_providers import ApifyToolProvider

    calls = []

    def handler(request):
        calls.append(request.method)
        assert request.method == "GET"
        return httpx.Response(200, json={"data": {
            "username": "curious_coder", "name": "facebook-ads-library-scraper",
        }})

    cap = next(c for c in build_default_capabilities() if c.id == "ads.meta.library")
    assert cap.read_only is False
    actor_caps = [c for c in build_default_capabilities()
                  if all(route.provider == "apify" for route in c.candidates)]
    assert len(actor_caps) == 8
    assert all(not c.read_only for c in actor_caps)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reg = CapabilityRegistry(ToolMesh([ApifyToolProvider(token="configured", client=client)]), [cap])
        with pytest.raises(ControlError, match="allow_side_effects"):
            await reg.preflight(cap.id, {})
        assert calls == []
        await reg.preflight(cap.id, {}, allow_side_effects=True)
        assert calls == ["GET"]
        missing = CapabilityRegistry(ToolMesh([ApifyToolProvider(token="", client=client)]), [cap])
        row = (await missing.resolve(cap.id))["resolved"][0]
        assert row["available"] is False
        assert row["reason_code"] == "not_configured"


class Wallet:
    def __init__(self):
        self.reservations = []
        self.finishes = []

    def reserve_tool_call(self, **kwargs):
        self.reservations.append(kwargs)
        return 3

    def finish_usage(self, *args, **kwargs):
        self.finishes.append(kwargs)


async def gateway_request(monkeypatch, reg, payload, *, app=None):
    identity = AuthIdentity("owner", "key", ["mcp:read", "mcp:execute"], "free", 100, "api_key")
    monkeypatch.setattr("internet_hands.mcp_gateway.authenticate_secret", lambda *_: identity)
    monkeypatch.setattr("internet_hands.tool_mcp.get_capability_registry", lambda: reg)
    wallet = Wallet()

    async def inner(scope, receive, send):
        assert current_auth.get() == identity
        await JSONResponse({"ok": True})(scope, receive, send)

    gateway = MCPGatewayASGI(app or inner, store=wallet)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(gateway), base_url="https://local.test") as http:
        response = await http.post("/mcp", headers={"Authorization": "Bearer test"}, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": payload,
        })
    assert current_auth.get() is None
    return response, wallet


@pytest.mark.parametrize("tool,args", [
    ("mesh_capability_execute", {"capability": "game.setup", "arguments": {}}),
    ("gaming_intel", {"requests": [{"capability": "game.setup", "arguments": {}}]}),
])
async def test_gateway_unavailable_calls_never_touch_wallet(monkeypatch, tool, args):
    provider = SetupProvider(configured=False)
    response, wallet = await gateway_request(monkeypatch, registry(provider), {"name": tool, "arguments": args})
    assert response.status_code == 409
    assert response.json()["error"] == "capability_unavailable"
    assert "x-credits-reserved" not in response.headers
    assert wallet.reservations == wallet.finishes == []
    assert provider.inspected_users == ["owner"]


async def test_gateway_available_call_still_uses_normal_metering(monkeypatch):
    provider = SetupProvider()
    response, wallet = await gateway_request(monkeypatch, registry(provider), {
        "name": "mesh_capability_execute", "arguments": {"capability": "game.setup", "arguments": {}},
    })
    assert response.status_code == 200
    assert response.headers["x-credits-reserved"] == "3"
    assert len(wallet.reservations) == len(wallet.finishes) == 1
    assert provider.inspected_users == ["owner"]


@pytest.mark.parametrize("args", [
    {"capability": "missing", "arguments": {}},
    {"capability": "game.setup", "arguments": "invalid"},
])
async def test_gateway_invalid_semantic_request_does_not_reserve(monkeypatch, args):
    response, wallet = await gateway_request(monkeypatch, registry(SetupProvider()), {
        "name": "mesh_capability_execute", "arguments": args,
    })
    assert response.status_code in {404, 422}
    assert wallet.reservations == wallet.finishes == []


async def test_gateway_resets_identity_when_preflight_is_cancelled(monkeypatch):
    class CancelledProvider(SetupProvider):
        async def describe(self, tool_id):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await gateway_request(monkeypatch, registry(CancelledProvider()), {
            "name": "mesh_capability_execute", "arguments": {"capability": "game.setup", "arguments": {}},
        })
    assert current_auth.get() is None


async def test_game_browser_discovery_and_execution_use_owned_identity(monkeypatch):
    from internet_hands import game_api

    class OwnedProvider(SetupProvider):
        async def execute(self, *args, **kwargs):
            assert current_auth.get().user_id == "owner"
            return {"status": "completed", "data": {"ok": True}}

    provider = OwnedProvider()
    reg = registry(provider)
    cap = reg.capabilities["game.setup"]
    identity = AuthIdentity("owner", "key", ["mcp:execute"], "free", 100, "api_key")
    wallet = Wallet()
    monkeypatch.setattr(game_api, "get_tool_mesh", lambda: reg.mesh)
    monkeypatch.setattr(game_api, "_require_user", lambda _: {"id": "owner", "email_verified": True})
    monkeypatch.setattr(game_api, "_game_capability", lambda *_: cap)
    monkeypatch.setattr(game_api, "_playground_identity", lambda *_: identity)
    monkeypatch.setattr(game_api, "store", wallet)
    options = await game_api.game_tool_options(None, "game", cap.id)
    assert len(options["tools"]) == 1
    result = await game_api._run_mesh_game_tool(None, {"ref": "setup:tool", "arguments": {}}, cap)
    assert result["ok"] is True
    assert provider.inspected_users and set(provider.inspected_users) == {"owner"}
    assert len(wallet.reservations) == len(wallet.finishes) == 1
    assert current_auth.get() is None


async def test_game_browser_unavailable_selection_does_not_reserve(monkeypatch):
    from fastapi import HTTPException

    from internet_hands import game_api

    reg = registry(SetupProvider(configured=False))
    identity = AuthIdentity("owner", "key", ["mcp:execute"], "free", 100, "api_key")
    wallet = Wallet()
    monkeypatch.setattr(game_api, "get_tool_mesh", lambda: reg.mesh)
    monkeypatch.setattr(game_api, "_playground_identity", lambda *_: identity)
    monkeypatch.setattr(game_api, "store", wallet)
    with pytest.raises(HTTPException) as error:
        await game_api._run_mesh_game_tool(None, {"ref": "setup:tool", "arguments": {}}, reg.capabilities["game.setup"])
    assert error.value.status_code == 409
    assert wallet.reservations == wallet.finishes == []
    assert current_auth.get() is None
