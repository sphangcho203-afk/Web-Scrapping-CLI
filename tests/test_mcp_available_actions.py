from __future__ import annotations

import pytest

from internet_hands.auth import current_auth
from internet_hands.capability_packs import Capability, CapabilityCandidate
from internet_hands.control_store import AuthIdentity
from internet_hands.mcp_access import available_actions, tool_allowed
from internet_hands.tool_mesh import ToolMesh


def _identity(user_id: str) -> AuthIdentity:
    return AuthIdentity(user_id, "key_1", ["mcp:read", "mcp:execute"], "free", 10, "api_key")


class _AccountProvider:
    name = "account_source"

    async def status(self):
        identity = current_auth.get()
        return {"sources": [identity.user_id if identity else "operator"], "executable": True}


@pytest.mark.asyncio
async def test_provider_status_cache_is_isolated_per_account() -> None:
    mesh = ToolMesh([_AccountProvider()])  # type: ignore[list-item]
    for user_id in ("alice", "bob", "alice"):
        token = current_auth.set(_identity(user_id))
        try:
            status = await mesh.provider_status()
            assert status["account_source"]["sources"] == [user_id]
        finally:
            current_auth.reset(token)


def test_plan_and_scopes_filter_mcp_tools() -> None:
    free = _identity("alice")
    assert tool_allowed(free, "mesh_search")
    assert tool_allowed(free, "account_available_actions")
    assert not tool_allowed(free, "sandbox_exec")
    assert not tool_allowed(free, "account_me")
    assert not tool_allowed(free, "monitors_list")


@pytest.mark.asyncio
async def test_available_actions_exclude_unconnected_and_dynamic_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    class Mesh:
        async def provider_status(self):
            return {
                "nativeweb": {"configured": True, "executable": True, "search_configured": False},
                "publicdata": {"configured": True, "executable": True},
                "composio": {"configured": True, "executable": True, "connected_toolkits": []},
            }

    class Registry:
        def __init__(self):
            self.capabilities = {
                name: Capability(
                    id=name, name=name, description=name, pack="web", tags=(),
                    candidates=(CapabilityCandidate(provider=provider, ref=ref),),
                )
                for name, provider, ref in (
                    ("fetch", "nativeweb", "nativeweb:fetch"),
                    ("extract", "publicdata", "publicdata:extract"),
                    ("search", "nativeweb", "nativeweb:search"),
                    ("app", "composio", "composio:send"),
                    ("dynamic", "nativeweb", None),
                )
            }

    monkeypatch.setattr("internet_hands.tool_mcp.get_tool_mesh", lambda: Mesh())
    monkeypatch.setattr("internet_hands.tool_mcp.get_capability_registry", lambda: Registry())
    result = await available_actions(_identity("alice"))
    assert [action["id"] for action in result["actions"]] == ["extract", "fetch"]


@pytest.mark.asyncio
async def test_available_actions_follow_subscription_provider_access(monkeypatch: pytest.MonkeyPatch) -> None:
    class Mesh:
        async def provider_status(self):
            return {"firecrawl": {"configured": True, "executable": True}}

    class Registry:
        def __init__(self):
            self.capabilities = {
            "scrape": Capability(
                id="scrape", name="Scrape", description="Scrape a page", pack="web",
                tags=(), candidates=(CapabilityCandidate(provider="firecrawl", ref="firecrawl:scrape"),),
            ),
            "unbounded": Capability(
                id="unbounded", name="Unbounded", description="Unquotable extraction", pack="web",
                tags=(), candidates=(CapabilityCandidate(provider="firecrawl", ref="firecrawl:extract"),),
            ),
            }

    monkeypatch.setattr("internet_hands.tool_mcp.get_tool_mesh", lambda: Mesh())
    monkeypatch.setattr("internet_hands.tool_mcp.get_capability_registry", lambda: Registry())
    assert (await available_actions(_identity("alice")))["actions"] == []
    paid = _identity("alice")
    paid.plan_slug = "builder"
    result = await available_actions(paid)
    assert [action["id"] for action in result["actions"]] == ["scrape"]
