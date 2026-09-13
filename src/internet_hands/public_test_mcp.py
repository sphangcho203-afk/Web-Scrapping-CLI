from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from . import tool_mcp as _tool_mcp
from .gaming_profiles import build_gaming_profile_plan

public_test_mcp = MCPServer(
    "Internet Hands Public Test",
    instructions=(
        "Public no-auth test surface for Internet Hands. This endpoint intentionally exposes "
        "discovery, routing, schema inspection, and gaming profile planning only. It does not "
        "expose sandbox execution, browser interaction, provider execution, secrets, or write tools."
    ),
)


def _transport_security() -> TransportSecuritySettings:
    hosts = {"127.0.0.1", "localhost"}
    for env_name in (
        "VERCEL_URL",
        "VERCEL_PROJECT_PRODUCTION_URL",
        "INTERNET_HANDS_PUBLIC_HOST",
    ):
        value = os.getenv(env_name, "").strip()
        if value:
            value = value.removeprefix("https://").removeprefix("http://").rstrip("/")
            hosts.add(value)
    allowed_hosts: list[str] = []
    allowed_origins: list[str] = []
    for host in sorted(hosts):
        allowed_hosts.extend([host, f"{host}:*"])
        if host in {"127.0.0.1", "localhost"}:
            allowed_origins.extend([f"http://{host}", f"http://{host}:*"])
        else:
            allowed_origins.append(f"https://{host}")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def streamable_http_app() -> Any:
    return public_test_mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=_transport_security(),
    )


@public_test_mcp.tool()
def test_ping() -> dict[str, Any]:
    """Verify the public Internet Hands MCP test server is reachable."""
    return {
        "ok": True,
        "server": "Internet Hands Public Test",
        "mode": "no-auth-read-only",
        "warning": "execution and sandbox tools are intentionally disabled on this public test endpoint",
    }


@public_test_mcp.tool()
async def mesh_providers() -> dict[str, Any]:
    """Report provider planes and whether each is configured, without exposing credentials."""
    return await _tool_mcp.get_tool_mesh().provider_status()


@public_test_mcp.tool()
async def mesh_route(
    intent: str,
    providers: list[str] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Route an intent to semantic capabilities and external tool candidates without executing."""
    intent = intent.strip()
    if not intent:
        raise ValueError("intent is required")
    raw = await _tool_mcp.get_tool_mesh().search(intent, providers=providers, limit=limit)
    semantic = _tool_mcp.get_capability_registry().list(query=intent, limit=min(limit, 20))
    return {
        "intent": intent,
        "capabilities": semantic["capabilities"],
        "tools": raw["tools"],
        "errors": raw["errors"],
        "execution_enabled": False,
    }


@public_test_mcp.tool()
async def mesh_search(
    query: str,
    providers: list[str] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Search provider catalogs and return normalized provider:tool references without execution."""
    return await _tool_mcp.get_tool_mesh().search(query, providers=providers, limit=limit)


@public_test_mcp.tool()
async def mesh_describe(ref: str) -> dict[str, Any]:
    """Inspect one normalized tool schema and metadata without executing it."""
    return await _tool_mcp.get_tool_mesh().describe(ref)


@public_test_mcp.tool()
def mesh_capabilities(
    query: str | None = None,
    pack: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List semantic capability packs."""
    return _tool_mcp.get_capability_registry().list(query=query, pack=pack, limit=limit)


@public_test_mcp.tool()
async def mesh_capability_resolve(capability: str) -> dict[str, Any]:
    """Resolve one semantic capability to ranked provider candidates and schemas without execution."""
    return await _tool_mcp.get_capability_registry().resolve(capability)


@public_test_mcp.tool()
def gaming_capabilities(
    game: str | None = None,
    query: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List public/read-only gaming intelligence capabilities."""
    return _tool_mcp.gaming_capabilities(game=game, query=query, limit=limit)


@public_test_mcp.tool()
def gaming_profile_plan(
    game: str,
    identity: dict[str, Any],
    include_recent: bool = True,
    include_history: bool = True,
) -> dict[str, Any]:
    """Plan the public evidence bundle for a player identity without making provider calls."""
    return build_gaming_profile_plan(
        game,
        identity,
        include_recent=include_recent,
        include_history=include_history,
    ).to_dict()
