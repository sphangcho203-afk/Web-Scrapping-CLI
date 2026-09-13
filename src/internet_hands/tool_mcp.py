from __future__ import annotations

from functools import lru_cache
from typing import Any

from .capability_packs import CapabilityRegistry, build_default_capabilities
from .catalog_providers import build_catalog_providers
from .mcp_server import sandbox_mcp
from .tool_mesh import ToolMesh
from .tool_providers import build_default_providers


@lru_cache(maxsize=1)
def get_tool_mesh() -> ToolMesh:
    return ToolMesh([*build_default_providers(), *build_catalog_providers()])


@lru_cache(maxsize=1)
def get_capability_registry() -> CapabilityRegistry:
    return CapabilityRegistry(get_tool_mesh(), build_default_capabilities())


@sandbox_mcp.tool()
async def mesh_providers() -> dict[str, Any]:
    """Report external tool providers, configuration state, and execution availability."""
    return await get_tool_mesh().provider_status()


@sandbox_mcp.tool()
async def mesh_search(
    query: str,
    providers: list[str] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Search external tool catalogs and return normalized provider:tool references."""
    return await get_tool_mesh().search(query, providers=providers, limit=limit)


@sandbox_mcp.tool()
async def mesh_describe(ref: str) -> dict[str, Any]:
    """Fetch the normalized input/output schema and metadata for one external tool."""
    return await get_tool_mesh().describe(ref)


@sandbox_mcp.tool()
async def mesh_execute(
    ref: str,
    arguments: dict[str, Any],
    account: str | None = None,
    wait_seconds: int = 30,
    timeout_seconds: int = 60,
    options: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute one normalized external tool; use dry_run to inspect the resolved call first."""
    return await get_tool_mesh().execute(
        ref,
        arguments,
        account=account,
        wait_seconds=wait_seconds,
        timeout_seconds=timeout_seconds,
        options=options,
        dry_run=dry_run,
    )


@sandbox_mcp.tool()
async def mesh_batch_execute(
    calls: list[dict[str, Any]],
    max_concurrency: int = 5,
) -> dict[str, Any]:
    """Execute independent external tool calls concurrently with bounded fan-out."""
    return await get_tool_mesh().batch_execute(calls, max_concurrency=max_concurrency)


@sandbox_mcp.tool()
async def mesh_job_status(
    provider: str,
    job_id: str,
    wait_seconds: int = 0,
) -> dict[str, Any]:
    """Inspect or briefly wait for a provider job such as a long-running Apify Actor run."""
    return await get_tool_mesh().job_status(provider, job_id, wait_seconds=wait_seconds)


@sandbox_mcp.tool()
async def mesh_results(
    provider: str,
    result_id: str,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Read one bounded page from a provider result store such as an Apify dataset."""
    return await get_tool_mesh().result_page(
        provider,
        result_id,
        offset=offset,
        limit=limit,
    )


@sandbox_mcp.tool()
def mesh_capabilities(
    query: str | None = None,
    pack: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List semantic capability packs such as MLBB without exposing provider-specific details."""
    return get_capability_registry().list(query=query, pack=pack, limit=limit)


@sandbox_mcp.tool()
async def mesh_capability_resolve(capability: str) -> dict[str, Any]:
    """Show ranked provider candidates and schemas for one semantic capability."""
    return await get_capability_registry().resolve(capability)


@sandbox_mcp.tool()
async def mesh_capability_execute(
    capability: str,
    arguments: dict[str, Any],
    provider_preference: str | None = None,
    dry_run: bool = False,
    wait_seconds: int = 30,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Execute a semantic capability using the best available read-only provider fallback."""
    return await get_capability_registry().execute(
        capability,
        arguments,
        provider_preference=provider_preference,
        dry_run=dry_run,
        wait_seconds=wait_seconds,
        timeout_seconds=timeout_seconds,
    )
