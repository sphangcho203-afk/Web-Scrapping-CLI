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
    ToolEconomics(
        "phone_caller_lookup",
        "caller_intelligence",
        4,
        minimum_plan="builder",
        provider_class="free_tier",
    ),
    ToolEconomics(
        "phone_caller_investigate",
        "caller_investigation",
        6,
        minimum_plan="builder",
        provider_class="free_tier",
    ),
    ToolEconomics("gaming_capabilities", "gaming", 1, provider_class="local"),
    ToolEconomics("gaming_profile_plan", "gaming", 1, provider_class="public"),
    ToolEconomics("gaming_profile", "gaming", 5, provider_class="public"),
    ToolEconomics("gaming_intel", "gaming", 2, provider_class="public"),
    ToolEconomics("mesh_capability_execute", "provider", 2, provider_class="public"),
    ToolEconomics("playground:*", "playground", 1, provider_class="public"),
    ToolEconomics("repo:*", "repository", 1, provider_class="public"),
    ToolEconomics("gamecore:*", "gaming", 1, provider_class="local"),
    ToolEconomics(
        "sandbox_browser_*",
        "browser",
        4,
        minimum_plan="builder",
        provider_class="public",
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
    "publicdata": ("public", 0),
    "gamepublic": ("public", 0),
    "phoneintel": ("local", 0),
    "callerintel": ("free_tier", 4),
    "callerresearch": ("free_tier", 6),
    "publicapi": ("public", 1),
    "openapi": ("public", 1),
    "mcp": ("public", 2),
    "composio": ("metered", 3),
    "firecrawl": ("metered", 250),
    "rapidapi": ("metered", 5),
    # The run is capped at $0.10 in ApifyToolProvider. At the least expensive
    # credit-pack rate, 1,500 credits represent INR 15 before payment fees.
    "apify": ("metered", 1500),
    "nativesandbox": ("metered", 10),
    "gamecore": ("local", 0),
    "githubpublic": ("public", 1),
}

FIRECRAWL_CREDITS_PER_UNIT = 250
FIRECRAWL_WORK_BUDGETS = {
    "crawl": ("limit", 10, 20),
    "map": ("limit", 10, 20),
    "search": ("limit", 5, 10),
    "agent": ("maxCredits", 10, 20),
}


def _semantic_calls(
    capability_id: str, arguments: dict[str, Any], plan: PlanPrivileges,
) -> tuple[list[CostEstimate], str | None]:
    # Resolve the same registered candidates used by execution. Price every
    # eligible fallback: a failed first attempt can still incur real work.
    from .tool_mcp import get_capability_registry

    registry = get_capability_registry()
    capability = registry.capabilities.get(capability_id)
    if capability is None:
        return [], f"unknown capability: {capability_id}"
    quotes: list[CostEstimate] = []
    for candidate in capability.candidates:
        if not registry._candidate_matches(arguments, candidate):
            continue
        ref = candidate.ref or f"{candidate.provider}:discovered"
        quote = estimate_call("mesh_execute", {"ref": ref, "arguments": registry._map_arguments(arguments, candidate)}, plan.slug)
        if quote.allowed:
            quotes.append(quote)
    if not quotes:
        return [], f"{capability_id} has no execution route on the {plan.slug} plan"
    return quotes, None


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


def _caller_cost(
    plan: PlanPrivileges,
    arguments: dict[str, Any],
) -> tuple[int, str, list[dict[str, Any]], str | None]:
    total = 4
    highest_class = "local"
    breakdown: list[dict[str, Any]] = [{"kind": "base", "credits": 4}]

    public_search = bool(arguments.get("public_search", True))
    if public_search:
        if not _provider_allowed(plan, "free_tier"):
            return (
                total,
                "free_tier",
                breakdown,
                "public caller attribution requires free_tier provider access",
            )
        total += 4
        highest_class = "free_tier"
        breakdown.append(
            {
                "kind": "public_search",
                "provider_class": "free_tier",
                "credits": 4,
            }
        )
        try:
            requested_results = max(1, min(int(arguments.get("max_results", 8)), 20))
        except (TypeError, ValueError):
            requested_results = 8
        plan_result_limit = min(20, max(5, plan.max_depth * 5))
        if requested_results > plan_result_limit:
            return (
                total,
                highest_class,
                breakdown,
                (
                    f"{plan.slug} allows at most {plan_result_limit} public caller "
                    "evidence results per lookup"
                ),
            )
        max_results = requested_results
        result_units = math.ceil(max_results / 5)
        total += result_units
        breakdown.append(
            {
                "kind": "result_budget",
                "units": result_units,
                "max_results": max_results,
                "credits": result_units,
            }
        )

    if bool(arguments.get("telecom_external", False)):
        providers = arguments.get("telecom_providers")
        phone_arguments = {
            "external": True,
            "providers": providers,
        }
        phone_total, phone_class, phone_breakdown, reason = _phone_cost(
            plan,
            phone_arguments,
        )
        if reason:
            return total, phone_class, breakdown, reason
        surcharge = max(0, phone_total - 2)
        total += surcharge
        breakdown.extend(
            item
            for item in phone_breakdown
            if item.get("kind") == "provider"
        )
        if PROVIDER_CLASS_ORDER[phone_class] > PROVIDER_CLASS_ORDER[highest_class]:
            highest_class = phone_class

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

    if tool_name.startswith("playground:"):
        operation = tool_name.split(":", 1)[1]
        # Reserve the bounded search and recovery fan-out. The final charge is
        # based on credits reported by providers and never exceeds this quote.
        search_budget = 2 if operation in {"search", "research", "auto"} and args.get("query") else 0
        recovery_budget = 3 if operation in {"research", "auto"} and args.get("query") else 0
        reserved = rule.base_credits + search_budget + recovery_budget
        return CostEstimate(
            allowed=True, plan=plan.slug, tool_name=tool_name,
            category=rule.category, credits=reserved,
            minimum_plan=rule.minimum_plan, provider_class=rule.provider_class,
            reason=None,
            breakdown=(
                {"kind": "base", "credits": rule.base_credits},
                {"kind": "search_budget", "credits": search_budget},
                {"kind": "recovery_budget", "credits": recovery_budget},
            ), limits=plan.to_dict(),
        )

    if tool_name in {"repo:search", "repo:inspect"}:
        budget = 2 if tool_name == "repo:search" else 6
        return CostEstimate(
            allowed=True, plan=plan.slug, tool_name=tool_name,
            category=rule.category, credits=rule.base_credits + budget,
            minimum_plan=rule.minimum_plan, provider_class=rule.provider_class,
            reason=None, breakdown=({"kind": "base", "credits": rule.base_credits},
                                    {"kind": "github_request_budget", "credits": budget}),
            limits=plan.to_dict(),
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

    if tool_name == "phone_caller_lookup":
        credits, provider_class, caller_breakdown, reason = _caller_cost(plan, args)
        return CostEstimate(
            allowed=reason is None,
            plan=plan.slug,
            tool_name=tool_name,
            category=rule.category,
            credits=credits,
            minimum_plan=rule.minimum_plan,
            provider_class=provider_class,
            reason=reason,
            breakdown=tuple(caller_breakdown),
            limits=plan.to_dict(),
        )

    if tool_name == "phone_caller_investigate":
        try:
            max_sources = max(1, min(int(args.get("max_sources", 4)), 12))
        except (TypeError, ValueError):
            max_sources = 4
        if max_sources > plan.max_external_sources:
            return CostEstimate(
                allowed=False, plan=plan.slug, tool_name=tool_name, category=rule.category,
                credits=6, minimum_plan=rule.minimum_plan, provider_class="free_tier",
                reason=f"{plan.slug} allows at most {plan.max_external_sources} deep caller evidence sources",
                breakdown=({"kind": "base", "credits": 6},), limits=plan.to_dict(),
            )
        caller_args = {"public_search": True, "max_results": min(20, max(5, max_sources * 2)), "telecom_external": bool(args.get("telecom_external", False)), "telecom_providers": args.get("telecom_providers")}
        caller_credits, provider_class, caller_breakdown, reason = _caller_cost(plan, caller_args)
        credits = caller_credits + max_sources
        breakdown = [*caller_breakdown, {"kind": "source_fetch_budget", "sources": max_sources, "credits": max_sources}]
        return CostEstimate(
            allowed=reason is None, plan=plan.slug, tool_name=tool_name, category=rule.category,
            credits=credits, minimum_plan=rule.minimum_plan, provider_class=provider_class,
            reason=reason, breakdown=tuple(breakdown), limits=plan.to_dict(),
        )

    if tool_name in {"mesh_capability_execute", "gaming_intel", "gaming_profile"}:
        reason: str | None = None
        phone_capabilities = {
            "phone.number.lookup", "phone.caller.lookup", "phone.caller.investigate",
        }
        if tool_name == "mesh_capability_execute":
            requests = [args]
        elif tool_name == "gaming_intel":
            requests = args.get("requests") or []
        else:
            from .gaming_profiles import build_gaming_profile_plan

            try:
                profile = build_gaming_profile_plan(
                    str(args.get("game") or ""), dict(args.get("identity") or {}),
                    include_recent=bool(args.get("include_recent", True)),
                    include_history=bool(args.get("include_history", True)),
                )
                requests = profile.requests
            except (ValueError, TypeError) as exc:
                requests = []
                reason = str(exc)
        if not isinstance(requests, list):
            requests, reason = [], "requests must be a list"
        if len(requests) > min(plan.max_batch_calls, 20):
            reason = f"plan allows at most {min(plan.max_batch_calls, 20)} capability calls"
        base = 0 if tool_name == "mesh_capability_execute" and str(args.get("capability")) in phone_capabilities else rule.base_credits
        cost = base
        breakdown = [{"kind": "base", "credits": base}]
        highest_class = rule.provider_class
        for index, request in enumerate(requests):
            if reason:
                break
            if not isinstance(request, dict):
                reason = f"capability call {index} must be an object"
                break
            capability = str(request.get("capability") or "").strip()
            nested_args = request.get("arguments") or {}
            if not isinstance(nested_args, dict):
                reason = f"capability call {index} arguments must be an object"
                break
            if capability in phone_capabilities:
                direct = {
                    "phone.number.lookup": "phone_number_lookup",
                    "phone.caller.lookup": "phone_caller_lookup",
                    "phone.caller.investigate": "phone_caller_investigate",
                }[capability]
                quotes = [estimate_call(direct, nested_args, plan.slug)]
            else:
                quotes, reason = _semantic_calls(capability, nested_args, plan)
            if reason:
                break
            for quote in quotes:
                if not quote.allowed:
                    reason = quote.reason
                    break
                cost += quote.credits
                breakdown.append({
                    "kind": "capability_attempt", "index": index,
                    "capability": capability, "credits": quote.credits,
                    "provider_class": quote.provider_class,
                })
                if PROVIDER_CLASS_ORDER[quote.provider_class] > PROVIDER_CLASS_ORDER[highest_class]:
                    highest_class = quote.provider_class
        if not requests and not reason and tool_name == "mesh_capability_execute":
            reason = "capability is required"
        return CostEstimate(
            allowed=reason is None, plan=plan.slug, tool_name=tool_name,
            category=rule.category, credits=cost, minimum_plan=rule.minimum_plan,
            provider_class=highest_class, reason=reason,
            breakdown=tuple(breakdown), limits=plan.to_dict(),
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

        if ref == "callerintel:lookup":
            nested = estimate_call(
                "phone_caller_lookup",
                nested_arguments,
                plan.slug,
            )
            return CostEstimate(
                allowed=nested.allowed,
                plan=plan.slug,
                tool_name=tool_name,
                category="caller_intelligence",
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

        if ref == "callerresearch:investigate":
            nested = estimate_call("phone_caller_investigate", nested_arguments, plan.slug)
            return CostEstimate(
                nested.allowed, plan.slug, tool_name, nested.category, nested.credits,
                nested.minimum_plan, nested.provider_class, nested.reason,
                ({"kind": "routed_tool", "ref": ref, "credits": 0}, *nested.breakdown),
                plan.to_dict(),
            )

        if ref in {"githubpublic:search", "githubpublic:inspect"}:
            nested = estimate_call("repo:" + ref.split(":", 1)[1], nested_arguments, plan.slug)
            return CostEstimate(
                nested.allowed, plan.slug, tool_name, nested.category, nested.credits,
                nested.minimum_plan, nested.provider_class, nested.reason,
                ({"kind": "routed_tool", "ref": ref, "credits": 0}, *nested.breakdown),
                plan.to_dict(),
            )

        if ref.startswith("nativeweb:"):
            operation = ref.split(":", 1)[1]
            reason = None
            if operation == "crawl":
                units = nested_arguments.get("max_pages", nested_arguments.get("limit", 25))
                if isinstance(units, bool) or not isinstance(units, int) or not 1 <= units <= 500:
                    reason, units = "crawl requires 1 to 500 pages", 0
                else:
                    units *= 2  # A distinct origin may require its own robots fetch.
            elif operation == "batch-fetch":
                urls = nested_arguments.get("urls")
                units = len(urls) if isinstance(urls, list) else 0
                if not 1 <= units <= 20:
                    reason = "batch fetch requires 1 to 20 URLs"
            elif operation in {"fetch", "map", "search"}:
                units = 1
            else:
                reason, units = "unknown native web operation", 0
            return CostEstimate(
                reason is None, plan.slug, tool_name, "public_data", 2 + units * 3,
                "free", "local", reason,
                ({"kind": "base", "credits": 2},
                 {"kind": "request_budget", "requests": units, "credits": units * 3}),
                plan.to_dict(),
            )

        if ref.startswith(("publicdata:", "gamepublic:")):
            from .public_data_provider import request_budget

            try:
                units = request_budget(ref.split(":", 1)[1], nested_arguments) if ref.startswith("publicdata:") else 1
                reason = None
            except ValueError as exc:
                units, reason = 0, str(exc)
            return CostEstimate(
                reason is None, plan.slug, tool_name, "public_data", 2 + units * 3,
                "free", "public", reason,
                ({"kind": "base", "credits": 2},
                 {"kind": "public_request_budget", "requests": units, "credits": units * 3}),
                plan.to_dict(),
            )

        if ref.startswith("firecrawl:"):
            operation = ref.split(":", 1)[1]
            if operation == "batch-scrape":
                urls = nested_arguments.get("urls")
                units = len(urls) if isinstance(urls, list) else 0
                reason = "batch scrape requires 1 to 20 URLs" if not 1 <= units <= 20 else None
            elif operation in FIRECRAWL_WORK_BUDGETS:
                field, default, maximum = FIRECRAWL_WORK_BUDGETS[operation]
                try:
                    units = int(nested_arguments.get(field, default))
                except (ValueError, TypeError):
                    units = 0
                reason = f"{operation} requires {field} between 1 and {maximum}" if not 1 <= units <= maximum else None
            else:
                units, reason = 1, None
            if operation == "extract":
                reason = "unbounded extraction cannot be quoted; use bounded agent execution"
            total = 2 + FIRECRAWL_CREDITS_PER_UNIT * units
            return CostEstimate(
                allowed=reason is None and _provider_allowed(plan, "metered"),
                plan=plan.slug, tool_name=tool_name, category=rule.category,
                credits=total, minimum_plan=rule.minimum_plan, provider_class="metered",
                reason=reason or (None if _provider_allowed(plan, "metered") else "this route requires metered access"),
                breakdown=({"kind": "base", "credits": 2},
                           {"kind": "work_budget", "units": units,
                            "credits": FIRECRAWL_CREDITS_PER_UNIT * units}),
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



def _measured_provider_surcharge(
    provider_calls: dict[str, Any],
) -> int:
    total = 0
    for provider, raw_count in provider_calls.items():
        economics = PHONE_PROVIDER_ECONOMICS.get(str(provider).lower())
        if economics is None:
            continue
        _, surcharge = economics
        try:
            count = max(0, int(raw_count))
        except (TypeError, ValueError):
            count = 0
        total += surcharge * count
    return total


def _measured_mesh_attempts(provider_calls: dict[str, Any], counters: dict[str, Any]) -> int:
    total = 0
    for provider, raw_count in provider_calls.items():
        try:
            count = max(0, int(raw_count))
        except (TypeError, ValueError):
            continue
        _, surcharge = RAW_PROVIDER_SURCHARGES.get(str(provider).lower(), ("public", 0))
        if provider == "githubpublic":
            total += count
        elif provider == "firecrawl":
            total += count * 2
        else:
            total += count * (2 + surcharge)
    try:
        units = max(0, int(counters.get("firecrawl_work_units") or 0))
    except (ValueError, TypeError):
        units = 0
    total += units * FIRECRAWL_CREDITS_PER_UNIT
    for counter in ("public_data_requests", "public_game_requests", "native_web_requests"):
        total += max(0, int(counters.get(counter) or 0)) * 3
    return total


def settle_measured_cost(
    tool_name: str,
    arguments: dict[str, Any] | None,
    plan_slug: str,
    *,
    reserved_credits: int,
    execution_usage: dict[str, Any] | None = None,
    latency_ms: int = 0,
) -> int:
    """Calculate a bounded post-run charge from measured work.

    The reservation remains the hard upper bound. Tools without measured pricing
    support keep their quoted reservation until they expose reliable work units.
    """
    reserved = max(0, int(reserved_credits))
    args = arguments or {}
    usage = execution_usage or {}
    counters = usage.get("counters") or {}
    provider_calls = usage.get("provider_calls") or {}
    if not isinstance(counters, dict):
        counters = {}
    if not isinstance(provider_calls, dict):
        provider_calls = {}

    if tool_name.startswith("playground:"):
        # Provider credits are a policy mapping of one internal credit per
        # reported external credit. Unknown/missing provider usage is recorded
        # separately and never guessed into a customer charge.
        reported = 0
        for item in usage.get("provider_usage") or []:
            if not isinstance(item, dict):
                continue
            value = item.get("credits_used")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                reported += max(0, int(value))
        return min(reserved, (1 if usage.get("completed") else 0) + reported)

    if tool_name in {"repo:search", "repo:inspect"}:
        try:
            requests = max(0, int(counters.get("github_api_calls") or 0))
        except (ValueError, TypeError):
            requests = 0
        return min(reserved, (1 if usage.get("completed") else 0) + requests)

    if tool_name.startswith("gamecore:"):
        return min(reserved, 1 if usage.get("completed") else 0)

    if tool_name in {"mesh_capability_execute", "gaming_intel", "gaming_profile", "mesh_batch_execute"}:
        if tool_name == "mesh_capability_execute":
            capability = str(args.get("capability") or "").strip()
            nested_args = args.get("arguments") or {}
            phone_tools = {
                "phone.number.lookup": "phone_number_lookup",
                "phone.caller.lookup": "phone_caller_lookup",
                "phone.caller.investigate": "phone_caller_investigate",
            }
            if capability in phone_tools:
                return settle_measured_cost(
                    phone_tools[capability], nested_args, plan_slug,
                    reserved_credits=reserved, execution_usage=usage, latency_ms=latency_ms,
                )
        base = _rule_for(tool_name).base_credits if provider_calls else 0
        actual = base + _measured_mesh_attempts(provider_calls, counters)
        if provider_calls.get("githubpublic"):
            try:
                github_requests = max(0, int(counters.get("github_api_calls") or 0))
            except (TypeError, ValueError):
                github_requests = 0
            actual += github_requests
        return min(reserved, actual)

    if tool_name == "mesh_execute":
        ref = str(args.get("ref") or args.get("tool") or "").strip().lower()
        nested_args = (
            dict(args.get("arguments") or {})
            if isinstance(args.get("arguments"), dict)
            else {}
        )
        if ref == "phoneintel:lookup":
            return settle_measured_cost(
                "phone_number_lookup",
                nested_args,
                plan_slug,
                reserved_credits=reserved,
                execution_usage=usage,
                latency_ms=latency_ms,
            )
        if ref == "callerintel:lookup":
            return settle_measured_cost(
                "phone_caller_lookup",
                nested_args,
                plan_slug,
                reserved_credits=reserved,
                execution_usage=usage,
                latency_ms=latency_ms,
            )
        if ref == "callerresearch:investigate":
            return settle_measured_cost(
                "phone_caller_investigate", nested_args, plan_slug,
                reserved_credits=reserved, execution_usage=usage, latency_ms=latency_ms,
            )
        if ref in {"githubpublic:search", "githubpublic:inspect"}:
            return settle_measured_cost(
                "repo:" + ref.split(":", 1)[1], nested_args, plan_slug,
                reserved_credits=reserved, execution_usage=usage, latency_ms=latency_ms,
            )

        prefix = ref.split(":", 1)[0] if ":" in ref else ""
        if prefix in {"firecrawl", "publicdata", "gamepublic", "nativeweb"}:
            return min(reserved, _measured_mesh_attempts(provider_calls, counters))
        economics = RAW_PROVIDER_SURCHARGES.get(prefix)
        if economics is not None:
            _, surcharge = economics
            try:
                calls = max(0, int(provider_calls.get(prefix) or 0))
            except (TypeError, ValueError):
                calls = 0
            actual = 2 + surcharge * calls
            return min(reserved, actual)

    if tool_name == "phone_number_lookup":
        actual = 2 + _measured_provider_surcharge(provider_calls)
        return min(reserved, actual)

    if tool_name == "phone_caller_lookup":
        actual = 4
        try:
            search_calls = max(0, int(counters.get("public_search_call") or 0))
        except (TypeError, ValueError):
            search_calls = 0
        try:
            result_count = max(0, int(counters.get("public_search_result") or 0))
        except (TypeError, ValueError):
            result_count = 0

        if search_calls:
            actual += 4 * search_calls
            actual += math.ceil(result_count / 5) if result_count else 0
        actual += _measured_provider_surcharge(provider_calls)
        return min(reserved, actual)

    if tool_name == "phone_caller_investigate":
        actual = 6
        try:
            search_calls = max(0, int(counters.get("public_search_call") or 0))
        except (TypeError, ValueError):
            search_calls = 0
        try:
            result_count = max(0, int(counters.get("public_search_result") or 0))
        except (TypeError, ValueError):
            result_count = 0
        try:
            fetch_count = max(0, int(counters.get("caller_source_fetch") or 0))
        except (TypeError, ValueError):
            fetch_count = 0
        if search_calls:
            actual += 4 * search_calls
            actual += math.ceil(result_count / 5) if result_count else 0
        actual += fetch_count
        actual += _measured_provider_surcharge(provider_calls)
        return min(reserved, actual)

    rule = _rule_for(tool_name)
    if (
        rule.category in {"browser", "sandbox"}
        and rule.unit_field
        and args.get(rule.unit_field) is not None
        and rule.credits_per_unit > 0
    ):
        elapsed = max(0, int(latency_ms))
        units = max(1, math.ceil(elapsed / max(1, rule.unit_size)))
        if rule.max_units is not None:
            units = min(units, rule.max_units)
        actual = rule.base_credits + units * rule.credits_per_unit
        return min(reserved, actual)

    return reserved
