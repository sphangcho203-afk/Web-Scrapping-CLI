from __future__ import annotations

from typing import Any

from .capability_economics import (
    RAW_PROVIDER_SURCHARGES,
    _plan_allowed,
    _provider_allowed,
    _rule_for,
    estimate_call,
    plan_privileges,
)
from .control_store import AuthIdentity

DISCOVERY_TOOLS = {
    "mesh_providers", "mesh_route", "mesh_search", "mesh_describe",
    "mesh_describe_many", "mesh_capabilities", "mesh_capability_resolve",
    "gaming_capabilities", "gaming_profile_plan", "account_available_actions",
}


def required_scope(tool_name: str) -> str:
    if tool_name == "account_available_actions":
        return "mcp:read"
    if tool_name.startswith("account_"):
        return "account:read"
    if tool_name.startswith("monitor_") or tool_name == "monitors_list":
        return "monitors:read"
    if tool_name in DISCOVERY_TOOLS:
        return "mcp:read"
    return "mcp:execute"


def scope_allowed(identity: AuthIdentity, scope: str) -> bool:
    return "*" in identity.scopes or scope in identity.scopes


def tool_allowed(identity: AuthIdentity, tool_name: str) -> bool:
    plan = plan_privileges(identity.plan_slug)
    rule = _rule_for(tool_name)
    return (
        scope_allowed(identity, required_scope(tool_name))
        and _plan_allowed(plan.slug, rule.minimum_plan)
        and _provider_allowed(plan, rule.provider_class)
        and (rule.category != "browser" or plan.browser_enabled)
        and (rule.category != "sandbox" or plan.sandbox_enabled)
    )


async def available_actions(
    identity: AuthIdentity, *, query: str = "", limit: int = 50
) -> dict[str, Any]:
    """Shortlist executable registered routes for this account, not the public catalog."""
    from .tool_mcp import get_capability_registry, get_tool_mesh

    if not scope_allowed(identity, "mcp:read") or not scope_allowed(identity, "mcp:execute"):
        return {"actions": [], "total": 0, "plan": identity.plan_slug}
    plan = plan_privileges(identity.plan_slug)
    statuses = await get_tool_mesh().provider_status()
    registry = get_capability_registry()
    words = query.casefold().split()
    actions: list[dict[str, Any]] = []
    for capability in registry.capabilities.values():
        if words and not all(
            word in f"{capability.name} {capability.description} {capability.id} {' '.join(capability.tags)}".casefold()
            for word in words
        ):
            continue
        routes = []
        for candidate in capability.candidates:
            # A dynamic search candidate is not proof that a specific operation
            # exists. Show only concrete routes with an executable provider.
            if not candidate.ref:
                continue
            status = statuses.get(candidate.provider) or {}
            if not status.get("executable") or status.get("configured") is False:
                continue
            if candidate.provider == "composio":
                # Connection and tool availability are account-specific; a
                # project API key alone is never sufficient evidence.
                continue
            if (
                candidate.provider == "nativeweb"
                and candidate.ref.endswith(":search")
                and not status.get("search_configured")
            ):
                continue
            if candidate.provider == "mcp":
                # A saved server does not prove this specific tool was synced.
                continue
            if candidate.ref == "firecrawl:extract":
                # This unbounded operation has no safe execution quote.
                continue
            provider_class = RAW_PROVIDER_SURCHARGES.get(
                candidate.ref.split(":", 1)[0], (None, 0)
            )[0]
            if provider_class is not None:
                eligible = _provider_allowed(plan, provider_class)
            else:
                eligible = estimate_call(
                    "mesh_execute", {"ref": candidate.ref}, identity.plan_slug
                ).allowed
            if not eligible:
                continue
            routes.append(candidate.ref)
        if routes:
            actions.append({
                "id": capability.id,
                "name": capability.name,
                "description": capability.description,
                "category": capability.pack,
                "read_only": capability.read_only,
                "route": routes[0],
                "invoke": "mesh_capability_execute",
            })
    actions.sort(key=lambda item: (item["category"], item["name"]))
    return {
        "actions": actions[:max(1, min(limit, 100))],
        "total": len(actions),
        "plan": identity.plan_slug,
        "note": "Routes are eligible now; upstream health and required inputs are checked at execution.",
    }
