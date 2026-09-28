from __future__ import annotations

import pytest

from internet_hands.auth import current_auth
from internet_hands.capability_packs import Capability, CapabilityCandidate
from internet_hands.control_store import AuthIdentity
from internet_hands.mcp_access import available_actions, tool_allowed
from internet_hands.tool_mcp import mesh_capabilities, mesh_describe, mesh_providers, mesh_search
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


@pytest.mark.asyncio
async def test_raw_discovery_and_describe_hide_routes_outside_the_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    class Mesh:
        def __init__(self):
            self.providers = {"nativeweb": object(), "apify": object()}

        async def provider_status(self):
            return {name: {"configured": True, "executable": True} for name in self.providers}

        async def search(self, query, *, providers=None, limit=10):
            return {"query": query, "tools": [
                {"provider": name, "ref": f"{name}:fetch"}
                for name in (providers or self.providers)
            ][:limit], "errors": {}}

        async def describe(self, ref):
            return {"ref": ref}

    monkeypatch.setattr("internet_hands.tool_mcp.get_tool_mesh", lambda: Mesh())
    free_token = current_auth.set(_identity("alice"))
    try:
        assert [tool["ref"] for tool in (await mesh_search("fetch"))["tools"]] == ["nativeweb:fetch"]
        assert set(await mesh_providers()) == {"nativeweb"}
        with pytest.raises(PermissionError):
            await mesh_describe("apify:fetch")
    finally:
        current_auth.reset(free_token)
    paid = _identity("alice")
    paid.plan_slug = "builder"
    paid_token = current_auth.set(paid)
    try:
        assert [tool["ref"] for tool in (await mesh_search("fetch"))["tools"]] == [
            "nativeweb:fetch", "apify:fetch",
        ]
        assert (await mesh_describe("apify:fetch"))["ref"] == "apify:fetch"
    finally:
        current_auth.reset(paid_token)


@pytest.mark.asyncio
async def test_semantic_catalog_filters_paid_only_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    class Mesh:
        async def provider_status(self):
            return {
                "nativeweb": {"configured": True, "executable": True},
                "apify": {"configured": True, "executable": True},
            }

    class Registry:
        def list(self, *, query=None, pack=None, limit=50):
            return {"capabilities": [{
                "id": "web.fetch", "name": "Fetch", "description": "Fetch a page", "pack": "web",
                "candidates": [
                    {"provider": "nativeweb", "ref": "nativeweb:fetch"},
                    {"provider": "apify", "ref": "apify:actor"},
                ],
            }]}

    monkeypatch.setattr("internet_hands.tool_mcp.get_tool_mesh", lambda: Mesh())
    monkeypatch.setattr("internet_hands.tool_mcp.get_capability_registry", lambda: Registry())
    token = current_auth.set(_identity("alice"))
    try:
        capabilities = (await mesh_capabilities())["capabilities"]
        assert [item["ref"] for item in capabilities[0]["candidates"]] == ["nativeweb:fetch"]
    finally:
        current_auth.reset(token)
