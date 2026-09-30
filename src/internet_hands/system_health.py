from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse

from .mcp_server import sandbox_mcp
from .monitor_executor import _scheduler_authorized
from .provider_reliability import provider_reliability
from .tool_mcp import get_capability_registry, get_tool_mesh

router = APIRouter()

_REQUIRED_MCP_TOOLS = frozenset(
    {
        "phone_caller_lookup",
        "phone_number_lookup",
        "mesh_providers",
        "mesh_route",
        "mesh_search",
        "mesh_describe",
        "mesh_describe_many",
        "mesh_execute",
        "mesh_batch_execute",
        "mesh_job_status",
        "mesh_results",
        "mesh_capabilities",
        "mesh_capability_resolve",
        "mesh_capability_execute",
        "gaming_capabilities",
        "gaming_intel",
        "gaming_profile_plan",
        "gaming_profile",
        "sandbox_create",
        "sandbox_get",
        "sandbox_exec",
        "sandbox_start",
        "sandbox_shell",
        "sandbox_command",
        "sandbox_commands",
        "sandbox_command_logs",
        "sandbox_kill",
        "sandbox_install",
        "sandbox_git_clone",
        "sandbox_read_file",
        "sandbox_artifact",
        "sandbox_write_file",
        "sandbox_mkdir",
        "sandbox_start_service",
        "sandbox_browser_screenshot",
        "sandbox_snapshot",
        "sandbox_fork",
        "sandbox_stop",
        "sandbox_delete",
        "account_me",
        "account_usage",
        "account_wallet",
        "account_limits",
        "monitors_list",
        "monitor_get",
        "sandbox_browser_prepare",
        "sandbox_browser_state",
        "sandbox_browser_open",
        "sandbox_browser_click",
        "sandbox_browser_fill",
        "sandbox_browser_press",
        "sandbox_browser_extract",
        "sandbox_browser_capture",
        "sandbox_browser_download",
        "sandbox_browser_trace",
        "sandbox_browser_close",
    }
)


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


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
    timeout_seconds = _env_float(
        "OPENCRAWL_HEALTH_CAPABILITY_TIMEOUT_SECONDS",
        8.0,
        minimum=0.25,
        maximum=60.0,
    )

    async def one(capability_id: str) -> dict[str, Any]:
        async with semaphore:
            try:
                resolved = await asyncio.wait_for(
                    registry.resolve(capability_id),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                return {
                    "id": capability_id,
                    "available": False,
                    "error": "capability health check timed out",
                    "error_class": "timeout",
                }
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


@router.get("/api/internal/providers/reliability")
async def provider_reliability_status(
    authorization: str | None = Header(default=None),
    provider: str | None = Query(default=None),
) -> dict[str, Any]:
    await _scheduler_authorized(authorization)
    if provider:
        return {
            "provider": provider_reliability.snapshot(provider),
            "diagnostics": provider_reliability.diagnostics(),
        }
    return {
        "providers": provider_reliability.snapshot(),
        "diagnostics": provider_reliability.diagnostics(),
    }


@router.post("/api/internal/providers/reliability/reset")
async def provider_reliability_reset(
    authorization: str | None = Header(default=None),
    provider: str | None = Query(default=None),
) -> dict[str, Any]:
    await _scheduler_authorized(authorization)
    provider_reliability.reset(provider)
    return {
        "ok": True,
        "provider": provider,
        "scope": (
            "runtime+shared"
            if provider_reliability.shared_configured()
            else "runtime-local"
        ),
    }


@router.get("/api/internal/system/health")
async def system_health(
    authorization: str | None = Header(default=None),
    deep: bool = Query(default=False),
    strict: bool = Query(default=False),
) -> Any:
    """Operational health for provider routing and semantic capability coverage."""
    await _scheduler_authorized(authorization)
    health_started = time.monotonic()

    mesh = get_tool_mesh()
    registry = get_capability_registry()
    providers = await mesh.provider_status()
    reliability = provider_reliability.snapshot()
    provider_rows = {
        name: {
            **status,
            "available": _provider_available(status),
            "execution_ready": _provider_available(status),
            "discoverable": _provider_discoverable(status),
            "runtime_reliability": reliability.get(
                name,
                provider_reliability.snapshot(name),
            ),
        }
        for name, status in providers.items()
    }

    registered_tools = await sandbox_mcp.list_tools()
    registered_names = sorted(tool.name for tool in registered_tools)
    registered_set = set(registered_names)
    schema_complete = all(isinstance(tool.input_schema, dict) for tool in registered_tools)
    missing_required_tools = sorted(_REQUIRED_MCP_TOOLS - registered_set)
    extra_tools = sorted(registered_set - _REQUIRED_MCP_TOOLS)
    mcp_surface_ok = (
        not missing_required_tools
        and len(registered_names) == len(registered_set)
        and schema_complete
    )

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
            "required_tools": len(_REQUIRED_MCP_TOOLS),
            "unique_tools": len(registered_set),
            "schema_complete": schema_complete,
            "surface_ok": mcp_surface_ok,
            "missing_required_tools": missing_required_tools,
            "extra_tools": extra_tools,
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
            "open_provider_circuits": sum(
                1
                for row in provider_rows.values()
                if (row.get("runtime_reliability") or {}).get("circuit_open")
            ),
            "degraded_runtime_providers": sum(
                1
                for row in provider_rows.values()
                if int((row.get("runtime_reliability") or {}).get("samples") or 0) > 0
                and int((row.get("runtime_reliability") or {}).get("score") or 0) < 50
            ),
        },
        "fallbacks": {
            "native_web_provider": "nativeweb",
            "native_web_tools": [
                "nativeweb:fetch",
                "nativeweb:scrape",
                "nativeweb:search",
                "nativeweb:context",
                "nativeweb:map",
                "nativeweb:crawl",
                "nativeweb:batch-fetch",
            ],
            "adaptive_provider_routing": {
                "enabled": provider_reliability.enabled(),
                "scope": (
                    "runtime+shared"
                    if provider_reliability.shared_configured()
                    else "runtime-local"
                ),
                "read_only_only": True,
                "write_replay": False,
                "diagnostics": provider_reliability.diagnostics(),
            },
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

    result["stability"] = {
        "health_duration_ms": max(
            0,
            int((time.monotonic() - health_started) * 1000),
        ),
        "provider_discovery_timeout_seconds": mesh.discovery_timeout_seconds,
        "provider_status_cache_seconds": mesh.provider_status_cache_seconds,
        "provider_default_max_concurrency": mesh.provider_max_concurrency,
        "capability_health_timeout_seconds": _env_float(
            "OPENCRAWL_HEALTH_CAPABILITY_TIMEOUT_SECONDS",
            8.0,
            minimum=0.25,
            maximum=60.0,
        ),
    }

    if strict and result["status"] != "healthy":
        return JSONResponse(status_code=503, content=result)
    return result
