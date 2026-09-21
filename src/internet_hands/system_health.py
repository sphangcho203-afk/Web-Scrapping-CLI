from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse

from .mcp_server import sandbox_mcp
from .monitor_executor import _scheduler_authorized
from .tool_mcp import get_capability_registry, get_tool_mesh

router = APIRouter()


def _provider_available(status: dict[str, Any]) -> bool:
    return bool(status.get("executable"))


def _provider_discoverable(status: dict[str, Any]) -> bool:
    return bool(
        status.get("searchable")
        or status.get("executable")
        or status.get("configured")
    )


async def _deep_capability_health(limit: int = 100) -> list[dict[str, Any]]:
    registry = get_capability_registry()
    capability_ids = sorted(registry.capabilities)[: max(1, min(limit, 100))]
    semaphore = asyncio.Semaphore(8)

    async def one(capability_id: str) -> dict[str, Any]:
        async with semaphore:
            try:
                resolved = await registry.resolve(capability_id)
            except Exception as exc:  # noqa: BLE001 - health boundary
                return {
                    "id": capability_id,
                    "available": False,
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                }
        rows = resolved.get("resolved") or []
        available = [row for row in rows if row.get("available")]
        return {
            "id": capability_id,
            "available": bool(available),
            "available_refs": [row.get("ref") for row in available if row.get("ref")],
            "candidate_count": len(rows),
            "failed": [
                {
                    "provider": (row.get("candidate") or {}).get("provider"),
                    "reason": row.get("reason"),
                }
                for row in rows
                if not row.get("available")
            ][:5],
        }

    return await asyncio.gather(*(one(capability_id) for capability_id in capability_ids))


@router.get("/api/internal/system/health")
async def system_health(
    authorization: str | None = Header(default=None),
    deep: bool = Query(default=False),
    strict: bool = Query(default=False),
) -> Any:
    """Operational health for provider routing and semantic capability coverage."""
    await _scheduler_authorized(authorization)

    mesh = get_tool_mesh()
    registry = get_capability_registry()
    providers = await mesh.provider_status()
    provider_rows = {
        name: {
            **status,
            "available": _provider_available(status),
            "execution_ready": _provider_available(status),
            "discoverable": _provider_discoverable(status),
        }
        for name, status in providers.items()
    }

    registered_tools = await sandbox_mcp.list_tools()
    registered_names = sorted(tool.name for tool in registered_tools)
    schema_complete = all(isinstance(tool.input_schema, dict) for tool in registered_tools)
    mcp_surface_ok = len(registered_names) == 54 and len(set(registered_names)) == 54 and schema_complete

    capabilities = list(registry.capabilities.values())
    provider_coverage: dict[str, list[str]] = {}
    single_provider: list[str] = []
    for capability in capabilities:
        candidate_providers = sorted({candidate.provider for candidate in capability.candidates})
        provider_coverage[capability.id] = candidate_providers
        if len(candidate_providers) == 1:
            single_provider.append(capability.id)

    result: dict[str, Any] = {
        "status": "healthy"
        if mcp_surface_ok and any(row["execution_ready"] for row in provider_rows.values())
        else "degraded",
        "providers": provider_rows,
        "mcp": {
            "registered_tools": len(registered_names),
            "expected_tools": 54,
            "unique_tools": len(set(registered_names)),
            "schema_complete": schema_complete,
            "surface_ok": mcp_surface_ok,
            "tools": registered_names,
        },
        "summary": {
            "provider_count": len(provider_rows),
            "available_providers": sum(
                1 for row in provider_rows.values() if row["execution_ready"]
            ),
            "discoverable_providers": sum(
                1 for row in provider_rows.values() if row["discoverable"]
            ),
            "semantic_capabilities": len(capabilities),
            "single_provider_capabilities": len(single_provider),
            "multi_provider_capabilities": len(capabilities) - len(single_provider),
        },
        "fallbacks": {
            "native_web_provider": "nativeweb",
            "native_web_tools": [
                "nativeweb:fetch",
                "nativeweb:search",
                "nativeweb:map",
                "nativeweb:crawl",
                "nativeweb:batch-fetch",
            ],
            "single_provider_capabilities": single_provider,
        },
    }

    if deep:
        checks = await _deep_capability_health()
        unavailable = [row["id"] for row in checks if not row.get("available")]
        result["deep"] = {
            "checks": checks,
            "available": len(checks) - len(unavailable),
            "unavailable": len(unavailable),
            "unavailable_capabilities": unavailable,
        }
        if unavailable:
            result["status"] = "degraded"

    if strict and result["status"] != "healthy":
        return JSONResponse(status_code=503, content=result)
    return result
