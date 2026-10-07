"""Resolve registered game capabilities into callable, read-only mesh tools."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from .capability_availability import REASONS, availability_exception

_BLOCKED_INPUTS = {"authorization", "cookie", "proxy-authorization", "x-api-key"}


def _safe_tool(tool: dict[str, Any], status: dict[str, Any], *, provider: str) -> bool:
    metadata = tool.get("metadata") or {}
    return (
        tool.get("provider") == provider
        and bool(status.get("executable"))
        and status.get("tool_availability", {}).get(tool.get("ref"), True) is not False
        and metadata.get("configured", True) is not False
        and str(metadata.get("method", "")).upper() in {"GET", "HEAD"}
        and not tool.get("side_effecting")
        and (provider != "openapi" or not tool.get("requires_auth"))
        and (provider != "openapi" or not re.search(
            r"/(?:user|users|account|accounts|player|players|auth)(?:/|$)",
            str(metadata.get("path", "")).casefold(),
        ))
    )


async def discover_game_tools(capability: Any, mesh: Any, *, limit: int = 12) -> dict[str, Any]:
    """Bound discovery to registered candidate refs; never accept a user supplied URL."""
    if not capability.read_only:
        return {"tools": [], "reasons": ["This capability is not read-only."]}
    deadline = time.monotonic() + 8.0
    try:
        statuses = await asyncio.wait_for(mesh.provider_status(), timeout=8.0)
    except Exception as exc:  # noqa: BLE001 - provider discovery boundary
        return {"tools": [], "reasons": [availability_exception(exc)["reason"]]}
    rows: list[dict[str, Any]] = []
    reasons: list[str] = []
    for candidate in sorted(capability.candidates, key=lambda item: item.priority):
        status = statuses.get(candidate.provider, {})
        if status.get("error"):
            reasons.append(REASONS["temporarily_unavailable"])
            continue
        if not status.get("executable"):
            reasons.append(REASONS["not_configured"])
            continue
        if candidate.ref:
            if status.get("tool_availability", {}).get(candidate.ref, True) is False:
                reasons.append(REASONS["not_configured"])
                continue
            try:
                found = [await asyncio.wait_for(mesh.describe(candidate.ref), timeout=max(0.001, deadline - time.monotonic()))]
            except Exception as exc:  # noqa: BLE001 - third-party schema inspection
                reasons.append(availability_exception(exc)["reason"])
                continue
        elif candidate.search:
            try:
                result = await asyncio.wait_for(mesh.search(candidate.search, providers=[candidate.provider], limit=30), timeout=max(0.001, deadline - time.monotonic()))
            except Exception as exc:  # noqa: BLE001 - third-party discovery
                reasons.append(availability_exception(exc)["reason"])
                continue
            found = result.get("tools") or []
            if not found:
                reasons.append(REASONS["temporarily_unavailable"] if result.get("errors") else REASONS["tool_not_found"])
            # Catalog scoring includes generic source names. Require a capability-specific
            # word in the operation name/path so unrelated operations cannot run here.
            anchor = re.findall(r"[a-z]+", capability.id.casefold())[-1]
            aliases = {"detail": "hero", "list": "hero", "reference": "rank", "analytics": "hero"}
            anchor = aliases.get(anchor, anchor)
            found = [tool for tool in found if anchor.rstrip("s") in
                     (str(tool.get("name", "")) + " " + str((tool.get("metadata") or {}).get("path", ""))).casefold()]
        else:
            continue
        for tool in found:
            if (tool.get("metadata") or {}).get("configured", True) is False:
                reasons.append(REASONS["not_configured"])
            if _safe_tool(tool, status, provider=candidate.provider) and not any(row["ref"] == tool["ref"] for row in rows):
                rows.append(tool)
                if len(rows) >= limit:
                    break
        if len(rows) >= limit:
            break
    if not rows and not reasons:
        reasons.append("No public read-only operation is available for this capability.")
    return {"tools": rows, "reasons": list(dict.fromkeys(reasons))}


def validate_game_arguments(tool: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("input_schema") or {}
    properties = schema.get("properties") or {}
    if len(arguments) > 30 or len(str(arguments)) > 12000:
        raise ValueError("Too many arguments or input too long")
    unknown = set(arguments) - set(properties)
    if unknown:
        raise ValueError("Unknown arguments: " + ", ".join(sorted(unknown)))
    missing = [key for key in schema.get("required") or [] if arguments.get(key) in (None, "")]
    if missing:
        raise ValueError("Missing required arguments: " + ", ".join(missing))
    clean: dict[str, Any] = {}
    for key, value in arguments.items():
        spec = properties[key]
        if key.casefold() in _BLOCKED_INPUTS or spec.get("x-in") == "header":
            raise ValueError("Header arguments are not available in the game runner")
        kind = spec.get("type", "string")
        if kind == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValueError(f"{key} must be an integer")
        if kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError(f"{key} must be a number")
        if kind == "boolean" and not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean")
        if kind == "string" and not isinstance(value, str):
            raise ValueError(f"{key} must be text")
        if isinstance(value, str) and len(value) > 512:
            raise ValueError(f"{key} is too long")
        if kind in {"integer", "number"} and value is not None:
            if "minimum" in spec and value < spec["minimum"]:
                raise ValueError(f"{key} is below the allowed minimum")
            if "maximum" in spec and value > spec["maximum"]:
                raise ValueError(f"{key} is above the allowed maximum")
            if key.casefold() in {"size", "count", "limit", "per_page"} and value > 100:
                raise ValueError(f"{key} may not exceed 100")
        if "enum" in spec and value not in spec["enum"]:
            raise ValueError(f"Invalid value for {key}")
        clean[key] = value
    return clean
