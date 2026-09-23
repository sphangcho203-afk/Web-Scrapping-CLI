"""Resolve registered game capabilities into callable, read-only mesh tools."""

from __future__ import annotations

import re
from typing import Any

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
    statuses = await mesh.provider_status()
    rows: list[dict[str, Any]] = []
    reasons: list[str] = []
    for candidate in sorted(capability.candidates, key=lambda item: item.priority):
        status = statuses.get(candidate.provider, {})
        if not status.get("executable"):
            reasons.append(f"{candidate.provider}: provider is not connected")
            continue
        if candidate.ref:
            if status.get("tool_availability", {}).get(candidate.ref, True) is False:
                reasons.append(f"{candidate.provider}: provider key required")
                continue
            try:
                found = [await mesh.describe(candidate.ref)]
            except (ValueError, LookupError, PermissionError) as exc:
                reasons.append(f"{candidate.provider}: {exc}")
                continue
        elif candidate.search:
            result = await mesh.search(candidate.search, providers=[candidate.provider], limit=30)
            found = result.get("tools") or []
            if not found:
                reasons.append(f"{candidate.provider}: {(result.get('errors') or {}).get(candidate.provider) or 'no matching operations found'}")
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
            if _safe_tool(tool, status, provider=candidate.provider) and not any(row["ref"] == tool["ref"] for row in rows):
                rows.append(tool)
                if len(rows) >= limit:
                    break
        if len(rows) >= limit:
            break
    if not rows and not reasons:
        reasons.append("No public read-only operation is available for this capability.")
    return {"tools": rows, "reasons": reasons}


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
