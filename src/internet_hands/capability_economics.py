from __future__ import annotations

import fnmatch
import math
from dataclasses import asdict, dataclass
from typing import Any

PLAN_ORDER = {
    "free": 0,
    "builder": 10,
    "pro": 20,
    "scale": 30,
}

PROVIDER_CLASS_ORDER = {
    "local": 0,
    "public": 5,
    "free_tier": 10,
    "metered": 20,
    "premium": 30,
}


@dataclass(frozen=True, slots=True)
class PlanPrivileges:
    slug: str
    access_level: str
    max_provider_class: str
    max_batch_calls: int
    max_external_sources: int
    max_depth: int
    browser_enabled: bool
    sandbox_enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PLAN_PRIVILEGES: dict[str, PlanPrivileges] = {
    "free": PlanPrivileges(
        slug="free",
        access_level="basic",
        max_provider_class="public",
        max_batch_calls=3,
        max_external_sources=0,
        max_depth=1,
        browser_enabled=False,
        sandbox_enabled=False,
    ),
    "builder": PlanPrivileges(
        slug="builder",
        access_level="standard",
        max_provider_class="free_tier",
        max_batch_calls=10,
        max_external_sources=3,
        max_depth=3,
        browser_enabled=True,
        sandbox_enabled=False,
    ),
    "pro": PlanPrivileges(
        slug="pro",
        access_level="advanced",
        max_provider_class="metered",
        max_batch_calls=20,
        max_external_sources=6,
        max_depth=6,
        browser_enabled=True,
        sandbox_enabled=True,
    ),
    "scale": PlanPrivileges(
        slug="scale",
        access_level="full",
        max_provider_class="premium",
        max_batch_calls=50,
        max_external_sources=12,
        max_depth=12,
        browser_enabled=True,
        sandbox_enabled=True,
    ),
}


@dataclass(frozen=True, slots=True)
class ToolEconomics:
    pattern: str
    category: str
    base_credits: int
    minimum_plan: str = "free"
    provider_class: str = "public"
    unit_field: str | None = None
    unit_size: int = 1
    credits_per_unit: int = 0
    max_units: int | None = None


TOOL_ECONOMICS: tuple[ToolEconomics, ...] = (
    ToolEconomics("account_*", "account", 0, provider_class="local"),
    ToolEconomics("monitors_list", "account", 0, provider_class="local"),
    ToolEconomics("monitor_get", "account", 0, provider_class="local"),
    ToolEconomics("mesh_providers", "discovery", 1, provider_class="local"),
    ToolEconomics("mesh_search", "discovery", 1, provider_class="local"),
    ToolEconomics("mesh_describe*", "discovery", 1, provider_class="local"),
    ToolEconomics("mesh_capabilities", "discovery", 1, provider_class="local"),
    ToolEconomics("mesh_capability_resolve", "discovery", 1, provider_class="local"),
    ToolEconomics("phone_number_lookup", "phone_intelligence", 2, provider_class="local"),
    ToolEconomics("gaming_capabilities", "gaming", 1, provider_class="local"),
    ToolEconomics("gaming_profile_plan", "gaming", 1, provider_class="public"),
    ToolEconomics("gaming_profile", "gaming", 5, provider_class="public"),
    ToolEconomics("gaming_intel", "gaming", 2, provider_class="public"),
    ToolEconomics(
        "sandbox_browser_*",
        "browser",
        4,
        minimum_plan="builder",
        provider_class="metered",
        unit_field="timeout_ms",
        unit_size=60_000,
        credits_per_unit=3,
        max_units=30,
    ),
    ToolEconomics(
        "sandbox_*",
        "sandbox",
        3,
        minimum_plan="pro",
        provider_class="metered",
        unit_field="timeout_ms",
        unit_size=60_000,
        credits_per_unit=5,
        max_units=30,
    ),
    ToolEconomics("mesh_execute", "provider", 2, provider_class="public"),
    ToolEconomics("mesh_batch_execute", "provider_batch", 2, provider_class="public"),
    ToolEconomics("mesh_job_status", "provider", 1, provider_class="public"),
    ToolEconomics("mesh_results", "provider", 1, provider_class="public"),
    ToolEconomics("*", "default", 1, provider_class="public"),
)


PHONE_PROVIDER_ECONOMICS: dict[str, tuple[str, int]] = {
    "veriphone": ("free_tier", 2),
    "abstract": ("free_tier", 2),
    "numverify": ("free_tier", 2),
    "twilio": ("metered", 8),
}


RAW_PROVIDER_SURCHARGES: dict[str, tuple[str, int]] = {
    "nativeweb": ("local", 0),
    "phoneintel": ("local", 0),
    "publicapi": ("public", 1),
    "openapi": ("public", 1),
    "mcp": ("public", 2),
    "composio": ("metered", 3),
    "firecrawl": ("metered", 5),
    "rapidapi": ("metered", 5),
    "apify": ("metered", 10),
}


@dataclass(frozen=True, slots=True)
class CostEstimate:
    allowed: bool
    plan: str
    tool_name: str
    category: str
    credits: int
    minimum_plan: str
    provider_class: str
    reason: str | None
    breakdown: tuple[dict[str, Any], ...]
    limits: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["breakdown"] = list(self.breakdown)
        return result


def plan_privileges(plan_slug: str) -> PlanPrivileges:
    return PLAN_PRIVILEGES.get(plan_slug, PLAN_PRIVILEGES["free"])


def _rule_for(tool_name: str) -> ToolEconomics:
    matches = [rule for rule in TOOL_ECONOMICS if fnmatch.fnmatch(tool_name, rule.pattern)]
    matches.sort(key=lambda rule: len(rule.pattern.replace("*", "")), reverse=True)
    return matches[0] if matches else TOOL_ECONOMICS[-1]


def _provider_allowed(plan: PlanPrivileges, provider_class: str) -> bool:
    return PROVIDER_CLASS_ORDER[provider_class] <= PROVIDER_CLASS_ORDER[plan.max_provider_class]


def _plan_allowed(plan_slug: str, minimum_plan: str) -> bool:
    return PLAN_ORDER.get(plan_slug, 0) >= PLAN_ORDER.get(minimum_plan, 0)


def _bounded_units(rule: ToolEconomics, arguments: dict[str, Any]) -> int:
    if not rule.unit_field or rule.credits_per_unit <= 0:
        return 0
    raw = arguments.get(rule.unit_field)
    if raw is None:
        return 0
    try:
        value = max(0, int(raw))
    except (TypeError, ValueError):
        return 0
    units = max(1, math.ceil(value / max(1, rule.unit_size)))
    if rule.max_units is not None:
        units = min(units, rule.max_units)
    return units


def _phone_cost(
    plan: PlanPrivileges,
    arguments: dict[str, Any],
) -> tuple[int, str, list[dict[str, Any]], str | None]:
    breakdown: list[dict[str, Any]] = [{"kind": "base", "credits": 2}]
    external = bool(arguments.get("external", True))
    if not external:
        return 2, "local", breakdown, None

    providers_raw = arguments.get("providers")
    providers = (
        [str(item).strip().lower() for item in providers_raw if str(item).strip()]
        if isinstance(providers_raw, list)
        else []
    )

    # No explicit provider list means the runtime must choose a plan-bounded provider
    # set before execution. We intentionally do not guess shared paid-provider spend here.
    if not providers:
        if not external:
            return 2, "local", breakdown, None
        return (
            2,
            "local",
            breakdown,
            "external phone intelligence requires an explicit provider list",
        )

    if len(providers) > plan.max_external_sources:
        return (
            2,
            plan.max_provider_class,
            breakdown,
            f"plan allows at most {plan.max_external_sources} external phone sources",
        )

    total = 2
    highest_class = "local"
    for provider in providers:
        economics = PHONE_PROVIDER_ECONOMICS.get(provider)
        if economics is None:
            return total, highest_class, breakdown, f"unknown phone provider: {provider}"
        provider_class, surcharge = economics
        if not _provider_allowed(plan, provider_class):
            return (
                total,
                provider_class,
                breakdown,
                f"{provider} requires {provider_class} provider access",
            )
        total += surcharge
        breakdown.append(
            {
                "kind": "provider",
                "provider": provider,
                "provider_class": provider_class,
                "credits": surcharge,
            }
        )
        if PROVIDER_CLASS_ORDER[provider_class] > PROVIDER_CLASS_ORDER[highest_class]:
            highest_class = provider_class
    return total, highest_class, breakdown, None


def estimate_call(
    tool_name: str,
    arguments: dict[str, Any] | None,
    plan_slug: str,
) -> CostEstimate:
    args = arguments or {}
    plan = plan_privileges(plan_slug)
    rule = _rule_for(tool_name)
    breakdown: list[dict[str, Any]] = [{"kind": "base", "credits": rule.base_credits}]

    if not _plan_allowed(plan.slug, rule.minimum_plan):
        return CostEstimate(
            allowed=False,
            plan=plan.slug,
            tool_name=tool_name,
            category=rule.category,
            credits=rule.base_credits,
            minimum_plan=rule.minimum_plan,
            provider_class=rule.provider_class,
            reason=f"{tool_name} requires {rule.minimum_plan} or higher",
            breakdown=tuple(breakdown),
            limits=plan.to_dict(),
        )

    if rule.category == "browser" and not plan.browser_enabled:
        return CostEstimate(
            False,
            plan.slug,
            tool_name,
            rule.category,
            rule.base_credits,
            rule.minimum_plan,
            rule.provider_class,
            "browser tools are unavailable on this plan",
            tuple(breakdown),
            plan.to_dict(),
        )

    if rule.category == "sandbox" and not plan.sandbox_enabled:
        return CostEstimate(
            False,
            plan.slug,
            tool_name,
            rule.category,
            rule.base_credits,
            rule.minimum_plan,
            rule.provider_class,
            "sandbox tools are unavailable on this plan",
            tuple(breakdown),
            plan.to_dict(),
        )

    if tool_name == "phone_number_lookup":
        credits, provider_class, phone_breakdown, reason = _phone_cost(plan, args)
        allowed = reason is None
        return CostEstimate(
            allowed=allowed,
            plan=plan.slug,
            tool_name=tool_name,
            category=rule.category,
            credits=credits,
            minimum_plan=rule.minimum_plan,
            provider_class=provider_class,
            reason=reason,
            breakdown=tuple(phone_breakdown),
            limits=plan.to_dict(),
        )

    cost = rule.base_credits
    provider_class = rule.provider_class

    if tool_name == "mesh_execute":
        ref = str(args.get("ref") or args.get("tool") or "").strip().lower()
        nested_arguments = (
            dict(args.get("arguments") or {})
            if isinstance(args.get("arguments"), dict)
            else {}
        )
        if ref == "phoneintel:lookup":
            nested = estimate_call(
                "phone_number_lookup",
                nested_arguments,
                plan.slug,
            )
            return CostEstimate(
                allowed=nested.allowed,
                plan=plan.slug,
                tool_name=tool_name,
                category="phone_intelligence",
                credits=nested.credits,
                minimum_plan=nested.minimum_plan,
                provider_class=nested.provider_class,
                reason=nested.reason,
                breakdown=(
                    {"kind": "routed_tool", "ref": ref, "credits": 0},
                    *nested.breakdown,
                ),
                limits=plan.to_dict(),
            )

        prefix = ref.split(":", 1)[0] if ":" in ref else ""
        if prefix in RAW_PROVIDER_SURCHARGES:
            raw_class, surcharge = RAW_PROVIDER_SURCHARGES[prefix]
            provider_class = raw_class
            if not _provider_allowed(plan, raw_class):
                return CostEstimate(
                    False,
                    plan.slug,
                    tool_name,
                    rule.category,
                    cost,
                    rule.minimum_plan,
                    raw_class,
                    f"{prefix} requires {raw_class} provider access",
                    tuple(breakdown),
                    plan.to_dict(),
                )
            cost += surcharge
            if surcharge:
                breakdown.append(
                    {
                        "kind": "provider",
                        "provider": prefix,
                        "provider_class": raw_class,
                        "credits": surcharge,
                    }
                )

    if tool_name == "mesh_batch_execute":
        calls = args.get("calls")
        count = len(calls) if isinstance(calls, list) else 0
        if count > plan.max_batch_calls:
            return CostEstimate(
                False,
                plan.slug,
                tool_name,
                rule.category,
                cost,
                rule.minimum_plan,
                provider_class,
                f"plan allows at most {plan.max_batch_calls} calls per batch",
                tuple(breakdown),
                plan.to_dict(),
            )
        if isinstance(calls, list):
            for index, call in enumerate(calls):
                if not isinstance(call, dict):
                    return CostEstimate(
                        False,
                        plan.slug,
                        tool_name,
                        rule.category,
                        cost,
                        rule.minimum_plan,
                        provider_class,
                        f"batch call {index} is not an object",
                        tuple(breakdown),
                        plan.to_dict(),
                    )
                nested = estimate_call("mesh_execute", call, plan.slug)
                if not nested.allowed:
                    return CostEstimate(
                        False,
                        plan.slug,
                        tool_name,
                        rule.category,
                        cost,
                        rule.minimum_plan,
                        nested.provider_class,
                        f"batch call {index}: {nested.reason}",
                        tuple(breakdown),
                        plan.to_dict(),
                    )
                cost += nested.credits
                breakdown.append(
                    {
                        "kind": "batch_call",
                        "index": index,
                        "credits": nested.credits,
                        "provider_class": nested.provider_class,
                    }
                )
                if (
                    PROVIDER_CLASS_ORDER[nested.provider_class]
                    > PROVIDER_CLASS_ORDER[provider_class]
                ):
                    provider_class = nested.provider_class

    if tool_name == "mesh_capability_execute":
        capability = str(args.get("capability") or "").strip()
        nested_arguments = (
            dict(args.get("arguments") or {})
            if isinstance(args.get("arguments"), dict)
            else {}
        )
        if capability == "phone.number.lookup":
            nested = estimate_call("phone_number_lookup", nested_arguments, plan.slug)
            return CostEstimate(
                allowed=nested.allowed,
                plan=plan.slug,
                tool_name=tool_name,
                category="phone_intelligence",
                credits=nested.credits,
                minimum_plan=nested.minimum_plan,
                provider_class=nested.provider_class,
                reason=nested.reason,
                breakdown=(
                    {
                        "kind": "semantic_capability",
                        "capability": capability,
                        "credits": 0,
                    },
                    *nested.breakdown,
                ),
                limits=plan.to_dict(),
            )

    units = _bounded_units(rule, args)
    if units:
        surcharge = units * rule.credits_per_unit
        cost += surcharge
        breakdown.append(
            {
                "kind": "runtime_units",
                "field": rule.unit_field,
                "units": units,
                "credits": surcharge,
            }
        )

    if not _provider_allowed(plan, provider_class):
        return CostEstimate(
            False,
            plan.slug,
            tool_name,
            rule.category,
            cost,
            rule.minimum_plan,
            provider_class,
            f"{tool_name} requires {provider_class} provider access",
            tuple(breakdown),
            plan.to_dict(),
        )

    return CostEstimate(
        allowed=True,
        plan=plan.slug,
        tool_name=tool_name,
        category=rule.category,
        credits=cost,
        minimum_plan=rule.minimum_plan,
        provider_class=provider_class,
        reason=None,
        breakdown=tuple(breakdown),
        limits=plan.to_dict(),
    )
