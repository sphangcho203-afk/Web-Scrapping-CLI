from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

from .capability_packs import CapabilityRegistry, build_default_capabilities
from .catalog_providers import build_catalog_providers
from .composio_bridge import ComposioBridgeProvider
from .firecrawl_capabilities import build_firecrawl_capabilities
from .firecrawl_provider import FirecrawlToolProvider
from .gaming_capabilities import build_gaming_capabilities
from .gaming_extra_capabilities import build_extra_gaming_capabilities
from .gaming_extra_providers import build_extra_gaming_providers
from .gaming_profiles import build_gaming_profile_plan
from .gaming_providers import build_gaming_providers
from .mcp_server import sandbox_mcp
from .native_sandbox_provider import NativeSandboxToolProvider
from .native_web_provider import NativeWebToolProvider
from .phone_intelligence import PhoneIntelligenceProvider
from .remote_mcp_provider import build_remote_mcp_provider
from .tool_mesh import ToolMesh
from .tool_providers import build_default_providers


@lru_cache(maxsize=1)
def get_tool_mesh() -> ToolMesh:
    return ToolMesh(
        [
            *[provider for provider in build_default_providers() if provider.name != "composio"],
            ComposioBridgeProvider(),
            FirecrawlToolProvider(),
            NativeWebToolProvider(),
            NativeSandboxToolProvider(),
            PhoneIntelligenceProvider(),
            *build_catalog_providers(),
            *build_gaming_providers(),
            *build_extra_gaming_providers(),
            build_remote_mcp_provider(),
        ]
    )


@lru_cache(maxsize=1)
def get_capability_registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        get_tool_mesh(),
        [
            *build_default_capabilities(),
            *build_firecrawl_capabilities(),
            *build_gaming_capabilities(),
            *build_extra_gaming_capabilities(),
        ],
    )


@sandbox_mcp.tool()
async def phone_number_lookup(
    number: str,
    region: str | None = None,
    external: bool = True,
    providers: list[str] | None = None,
) -> dict[str, Any]:
    """Inspect telecom metadata and risk signals for a phone number without identifying a private subscriber."""
    result = await get_tool_mesh().execute(
        "phoneintel:lookup",
        {
            "number": number,
            "region": region,
            "external": external,
            "providers": providers,
        },
    )
    return result


@sandbox_mcp.tool()
async def mesh_providers() -> dict[str, Any]:
    """Report external tool providers, configuration state, and execution availability."""
    return await get_tool_mesh().provider_status()


@sandbox_mcp.tool()
async def mesh_route(
    intent: str,
    providers: list[str] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Route an agent intent to semantic capabilities and raw catalog tools without executing."""
    intent = intent.strip()
    if not intent:
        raise ValueError("intent is required")
    raw = await get_tool_mesh().search(intent, providers=providers, limit=limit)
    semantic = get_capability_registry().list(query=intent, limit=min(limit, 20))
    return {
        "intent": intent,
        "capabilities": semantic["capabilities"],
        "tools": raw["tools"],
        "errors": raw["errors"],
        "next": "resolve a capability or describe shortlisted tool refs before execution",
    }


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
async def mesh_describe_many(refs: list[str]) -> dict[str, Any]:
    """Fetch schemas for up to 20 shortlisted tools in parallel."""
    if not refs:
        return {"tools": [], "errors": {}}
    if len(refs) > 20:
        raise ValueError("mesh_describe_many accepts at most 20 refs")

    async def one(ref: str) -> tuple[str, dict[str, Any] | None, str | None]:
        try:
            return ref, await get_tool_mesh().describe(ref), None
        except Exception as exc:  # noqa: BLE001 - isolate external descriptor failures
            return ref, None, str(exc)

    rows = await asyncio.gather(*(one(ref) for ref in refs))
    return {
        "tools": [tool for _, tool, _ in rows if tool is not None],
        "errors": {ref: error for ref, _, error in rows if error},
    }


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
    """Inspect or briefly wait for a provider job such as a long-running Apify or Firecrawl run."""
    return await get_tool_mesh().job_status(provider, job_id, wait_seconds=wait_seconds)


@sandbox_mcp.tool()
async def mesh_results(
    provider: str,
    result_id: str,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Read one bounded page from a provider result store or async crawl/batch result."""
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
    """List semantic capability packs without exposing provider-specific details."""
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
    account: str | None = None,
    allow_side_effects: bool = False,
    dry_run: bool = False,
    wait_seconds: int = 30,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Execute a semantic capability with explicit gating for side-effecting operations."""
    return await get_capability_registry().execute(
        capability,
        arguments,
        provider_preference=provider_preference,
        account=account,
        allow_side_effects=allow_side_effects,
        dry_run=dry_run,
        wait_seconds=wait_seconds,
        timeout_seconds=timeout_seconds,
    )


@sandbox_mcp.tool()
def gaming_capabilities(
    game: str | None = None,
    query: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List gaming intelligence capabilities, optionally scoped to one game/pack."""
    result = get_capability_registry().list(query=query, pack=game, limit=limit)
    gaming = [
        item
        for item in result["capabilities"]
        if "gaming" in item.get("tags", []) or item.get("pack") == "mlbb"
    ]
    return {"game": game, "capabilities": gaming}


@sandbox_mcp.tool()
async def gaming_intel(
    requests: list[dict[str, Any]],
    max_concurrency: int = 5,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run up to 20 independent read-only gaming intelligence capabilities in parallel."""
    if not requests:
        return {"results": []}
    if len(requests) > 20:
        raise ValueError("gaming_intel accepts at most 20 requests")

    registry = get_capability_registry()
    semaphore = asyncio.Semaphore(max(1, min(max_concurrency, 10)))

    async def one(index: int, request: dict[str, Any]) -> dict[str, Any]:
        capability_id = str(request.get("capability") or "").strip()
        capability = registry.capabilities.get(capability_id)
        if capability is None:
            return {
                "index": index,
                "capability": capability_id,
                "status": "failed",
                "error": "unknown capability",
            }
        if "gaming" not in capability.tags and capability.pack != "mlbb":
            return {
                "index": index,
                "capability": capability_id,
                "status": "failed",
                "error": "capability is not part of the gaming intelligence plane",
            }
        async with semaphore:
            result = await registry.execute(
                capability_id,
                dict(request.get("arguments") or {}),
                provider_preference=request.get("provider_preference"),
                dry_run=dry_run,
                wait_seconds=int(request.get("wait_seconds", 30)),
                timeout_seconds=int(request.get("timeout_seconds", 60)),
            )
        execution = result.get("execution") or {}
        return {
            "index": index,
            "capability": capability_id,
            "status": execution.get("status")
            or ("failed" if result.get("error") else "completed"),
            "selected": result.get("selected"),
            "attempts": result.get("attempts", []),
            "data": execution.get("data"),
            "error": execution.get("error") or result.get("error"),
            "duration_ms": result.get("duration_ms"),
        }

    results = await asyncio.gather(
        *(one(index, request) for index, request in enumerate(requests))
    )
    results.sort(key=lambda item: item["index"])
    return {"results": results}


@sandbox_mcp.tool()
def gaming_profile_plan(
    game: str,
    identity: dict[str, Any],
    include_recent: bool = True,
    include_history: bool = True,
) -> dict[str, Any]:
    """Plan the evidence bundle needed for one public player profile without executing it."""
    return build_gaming_profile_plan(
        game,
        identity,
        include_recent=include_recent,
        include_history=include_history,
    ).to_dict()


@sandbox_mcp.tool()
async def gaming_profile(
    game: str,
    identity: dict[str, Any],
    include_recent: bool = True,
    include_history: bool = True,
    max_concurrency: int = 5,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fetch the default public evidence bundle for a game/player identity in one call."""
    plan = build_gaming_profile_plan(
        game,
        identity,
        include_recent=include_recent,
        include_history=include_history,
    )
    evidence = await gaming_intel(
        plan.requests,
        max_concurrency=max_concurrency,
        dry_run=dry_run,
    )
    return {"plan": plan.to_dict(), "evidence": evidence["results"]}
