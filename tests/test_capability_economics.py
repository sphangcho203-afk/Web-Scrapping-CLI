from __future__ import annotations

from internet_hands.capability_economics import (
    estimate_call,
    plan_privileges,
    settle_measured_cost,
)


def test_every_plan_has_real_tool_calling_privileges() -> None:
    free = plan_privileges("free")
    builder = plan_privileges("builder")
    pro = plan_privileges("pro")
    scale = plan_privileges("scale")

    assert free.max_batch_calls >= 3
    assert free.max_depth >= 1
    assert builder.browser_enabled is True
    assert pro.sandbox_enabled is True
    assert scale.max_external_sources > pro.max_external_sources
    assert scale.max_batch_calls > builder.max_batch_calls


def test_phone_lookup_is_cheap_locally_for_free_plan() -> None:
    estimate = estimate_call(
        "phone_number_lookup",
        {"number": "+14155552671", "external": False},
        "free",
    )
    assert estimate.allowed is True
    assert estimate.credits == 2
    assert estimate.provider_class == "local"


def test_external_phone_sources_require_explicit_provider_selection() -> None:
    estimate = estimate_call(
        "phone_number_lookup",
        {"number": "+14155552671", "external": True},
        "free",
    )
    assert estimate.allowed is False
    assert estimate.credits == 2
    assert "explicit provider list" in (estimate.reason or "")


def test_builder_can_use_free_tier_phone_enrichment() -> None:
    estimate = estimate_call(
        "phone_number_lookup",
        {
            "number": "+14155552671",
            "providers": ["veriphone", "abstract"],
        },
        "builder",
    )
    assert estimate.allowed is True
    assert estimate.credits == 6
    assert estimate.provider_class == "free_tier"


def test_builder_cannot_use_metered_twilio_lookup() -> None:
    estimate = estimate_call(
        "phone_number_lookup",
        {"number": "+14155552671", "providers": ["twilio"]},
        "builder",
    )
    assert estimate.allowed is False
    assert "metered" in (estimate.reason or "")


def test_pro_can_use_metered_twilio_lookup_at_higher_cost() -> None:
    estimate = estimate_call(
        "phone_number_lookup",
        {"number": "+14155552671", "providers": ["twilio"]},
        "pro",
    )
    assert estimate.allowed is True
    assert estimate.credits == 10
    assert estimate.provider_class == "metered"


def test_raw_provider_costs_are_not_flat() -> None:
    local = estimate_call(
        "mesh_execute",
        {"ref": "nativeweb:fetch"},
        "pro",
    )
    firecrawl = estimate_call(
        "mesh_execute",
        {"ref": "firecrawl:scrape"},
        "pro",
    )
    apify = estimate_call(
        "mesh_execute",
        {"ref": "apify:actor"},
        "pro",
    )
    assert local.credits == 2
    assert firecrawl.credits == 7
    assert apify.credits == 12


def test_free_plan_can_use_public_raw_tools_but_not_metered_backends() -> None:
    public = estimate_call(
        "mesh_execute",
        {"ref": "publicapi:lookup"},
        "free",
    )
    paid = estimate_call(
        "mesh_execute",
        {"ref": "apify:actor"},
        "free",
    )
    assert public.allowed is True
    assert paid.allowed is False


def test_batch_limits_scale_with_subscription() -> None:
    free = estimate_call(
        "mesh_batch_execute",
        {"calls": [{}, {}, {}, {}]},
        "free",
    )
    scale = estimate_call(
        "mesh_batch_execute",
        {"calls": [{} for _ in range(40)]},
        "scale",
    )
    assert free.allowed is False
    assert scale.allowed is True
    assert scale.credits == 82


def test_runtime_pricing_accounts_for_requested_time() -> None:
    estimate = estimate_call(
        "sandbox_exec",
        {"timeout_ms": 180_000},
        "pro",
    )
    assert estimate.allowed is True
    assert estimate.credits == 18


def test_higher_plans_expand_privileges_not_privacy_boundaries() -> None:
    # Economics/access is plan-aware. Privacy/output policy is intentionally not
    # represented as a purchasable entitlement in this module.
    assert "privacy" not in plan_privileges("scale").to_dict()


def test_builder_browser_is_allowed_and_runtime_metered() -> None:
    estimate = estimate_call(
        "sandbox_browser_open",
        {"timeout_ms": 120_000},
        "builder",
    )
    assert estimate.allowed is True
    assert estimate.credits == 10


def test_nested_phone_lookup_through_mesh_execute_keeps_same_price() -> None:
    direct = estimate_call(
        "phone_number_lookup",
        {
            "number": "+14155552671",
            "external": True,
            "providers": ["veriphone", "abstract"],
        },
        "builder",
    )
    nested = estimate_call(
        "mesh_execute",
        {
            "ref": "phoneintel:lookup",
            "arguments": {
                "number": "+14155552671",
                "external": True,
                "providers": ["veriphone", "abstract"],
            },
        },
        "builder",
    )
    assert direct.allowed is True
    assert nested.allowed is True
    assert nested.credits == direct.credits


def test_semantic_phone_lookup_keeps_same_price() -> None:
    direct = estimate_call(
        "phone_number_lookup",
        {
            "number": "+14155552671",
            "external": True,
            "providers": ["twilio"],
        },
        "pro",
    )
    semantic = estimate_call(
        "mesh_capability_execute",
        {
            "capability": "phone.number.lookup",
            "arguments": {
                "number": "+14155552671",
                "external": True,
                "providers": ["twilio"],
            },
        },
        "pro",
    )
    assert semantic.allowed is True
    assert semantic.credits == direct.credits


def test_batch_pricing_sums_nested_provider_costs() -> None:
    estimate = estimate_call(
        "mesh_batch_execute",
        {
            "calls": [
                {"ref": "nativeweb:fetch", "arguments": {"url": "https://example.com"}},
                {"ref": "firecrawl:scrape", "arguments": {"url": "https://example.com"}},
            ]
        },
        "pro",
    )
    assert estimate.allowed is True
    assert estimate.credits == 11


def test_caller_lookup_requires_builder_or_higher() -> None:
    free = estimate_call(
        "phone_caller_lookup",
        {"number": "+14155552671"},
        "free",
    )
    builder = estimate_call(
        "phone_caller_lookup",
        {"number": "+14155552671"},
        "builder",
    )
    assert free.allowed is False
    assert builder.allowed is True


def test_caller_lookup_price_tracks_public_search_budget() -> None:
    no_search = estimate_call(
        "phone_caller_lookup",
        {
            "number": "+14155552671",
            "public_search": False,
        },
        "builder",
    )
    search = estimate_call(
        "phone_caller_lookup",
        {
            "number": "+14155552671",
            "public_search": True,
            "max_results": 8,
        },
        "builder",
    )
    assert no_search.credits == 4
    assert search.credits == 10


def test_caller_lookup_can_add_paid_telecom_intelligence_on_pro() -> None:
    estimate = estimate_call(
        "phone_caller_lookup",
        {
            "number": "+14155552671",
            "public_search": True,
            "max_results": 8,
            "telecom_external": True,
            "telecom_providers": ["twilio"],
        },
        "pro",
    )
    assert estimate.allowed is True
    assert estimate.credits == 18
    assert estimate.provider_class == "metered"


def test_caller_lookup_has_same_price_through_raw_mesh_route() -> None:
    direct = estimate_call(
        "phone_caller_lookup",
        {
            "number": "+14155552671",
            "public_search": True,
            "max_results": 5,
        },
        "builder",
    )
    routed = estimate_call(
        "mesh_execute",
        {
            "ref": "callerintel:lookup",
            "arguments": {
                "number": "+14155552671",
                "public_search": True,
                "max_results": 5,
            },
        },
        "builder",
    )
    assert routed.allowed is True
    assert routed.credits == direct.credits


def test_caller_lookup_has_same_price_through_semantic_route() -> None:
    direct = estimate_call(
        "phone_caller_lookup",
        {
            "number": "+14155552671",
            "public_search": True,
            "max_results": 5,
        },
        "builder",
    )
    semantic = estimate_call(
        "mesh_capability_execute",
        {
            "capability": "phone.caller.lookup",
            "arguments": {
                "number": "+14155552671",
                "public_search": True,
                "max_results": 5,
            },
        },
        "builder",
    )
    assert semantic.allowed is True
    assert semantic.credits == direct.credits


def test_caller_evidence_breadth_scales_with_plan() -> None:
    builder = estimate_call(
        "phone_caller_lookup",
        {
            "number": "+14155552671",
            "public_search": True,
            "max_results": 20,
        },
        "builder",
    )
    pro = estimate_call(
        "phone_caller_lookup",
        {
            "number": "+14155552671",
            "public_search": True,
            "max_results": 20,
        },
        "pro",
    )
    assert builder.allowed is False
    assert "at most 15" in (builder.reason or "")
    assert pro.allowed is True



def test_measured_caller_cost_releases_unused_result_budget() -> None:
    settled = settle_measured_cost(
        "phone_caller_lookup",
        {
            "number": "+14155552671",
            "public_search": True,
            "max_results": 8,
        },
        "builder",
        reserved_credits=10,
        execution_usage={
            "counters": {
                "public_search_call": 1,
                "public_search_result": 3,
            },
            "provider_calls": {"brave": 1},
        },
        latency_ms=1200,
    )
    assert settled == 9


def test_measured_caller_cost_refunds_search_when_provider_never_ran() -> None:
    settled = settle_measured_cost(
        "phone_caller_lookup",
        {
            "number": "+14155552671",
            "public_search": True,
            "max_results": 8,
        },
        "builder",
        reserved_credits=10,
        execution_usage={"counters": {}, "provider_calls": {}},
        latency_ms=50,
    )
    assert settled == 4


def test_measured_phone_cost_uses_only_providers_actually_called() -> None:
    settled = settle_measured_cost(
        "phone_number_lookup",
        {
            "number": "+14155552671",
            "external": True,
            "providers": ["veriphone", "abstract"],
        },
        "builder",
        reserved_credits=6,
        execution_usage={
            "counters": {},
            "provider_calls": {"veriphone": 1},
        },
        latency_ms=200,
    )
    assert settled == 4


def test_measured_phone_cost_survives_raw_mesh_routing() -> None:
    settled = settle_measured_cost(
        "mesh_execute",
        {
            "ref": "phoneintel:lookup",
            "arguments": {
                "number": "+14155552671",
                "external": True,
                "providers": ["veriphone", "abstract"],
            },
        },
        "builder",
        reserved_credits=6,
        execution_usage={
            "counters": {},
            "provider_calls": {"abstract": 1},
        },
        latency_ms=200,
    )
    assert settled == 4


def test_measured_sandbox_runtime_can_release_timeout_headroom() -> None:
    settled = settle_measured_cost(
        "sandbox_exec",
        {"timeout_ms": 180_000},
        "pro",
        reserved_credits=18,
        execution_usage={"counters": {}, "provider_calls": {}},
        latency_ms=12_000,
    )
    assert settled == 8



def test_measured_raw_provider_refunds_surcharge_when_not_executed() -> None:
    settled = settle_measured_cost(
        "mesh_execute",
        {
            "ref": "apify:actor",
            "arguments": {"query": "example"},
        },
        "pro",
        reserved_credits=12,
        execution_usage={"counters": {}, "provider_calls": {}},
        latency_ms=25,
    )
    assert settled == 2


def test_measured_raw_provider_keeps_surcharge_when_executed() -> None:
    settled = settle_measured_cost(
        "mesh_execute",
        {
            "ref": "apify:actor",
            "arguments": {"query": "example"},
        },
        "pro",
        reserved_credits=12,
        execution_usage={
            "counters": {},
            "provider_calls": {"apify": 1},
        },
        latency_ms=500,
    )
    assert settled == 12


def test_measured_firecrawl_provider_settles_to_its_actual_route() -> None:
    settled = settle_measured_cost(
        "mesh_execute",
        {
            "ref": "firecrawl:scrape",
            "arguments": {"url": "https://example.com"},
        },
        "pro",
        reserved_credits=7,
        execution_usage={
            "counters": {},
            "provider_calls": {"firecrawl": 1},
        },
        latency_ms=500,
    )
    assert settled == 7


def test_caller_investigate_requires_pro_or_higher() -> None:
    builder = estimate_call(
        "phone_caller_investigate",
        {"number": "+14155552671"},
        "builder",
    )
    pro = estimate_call(
        "phone_caller_investigate",
        {"number": "+14155552671"},
        "pro",
    )
    assert builder.allowed is False
    assert pro.allowed is True


def test_caller_investigate_reserves_page_budget() -> None:
    estimate = estimate_call(
        "phone_caller_investigate",
        {
            "number": "+14155552671",
            "max_search_results": 10,
            "max_pages": 4,
        },
        "pro",
    )
    assert estimate.allowed is True
    assert estimate.credits == 26


def test_caller_investigate_page_limit_scales_with_plan() -> None:
    pro = estimate_call(
        "phone_caller_investigate",
        {
            "number": "+14155552671",
            "max_pages": 8,
        },
        "pro",
    )
    scale = estimate_call(
        "phone_caller_investigate",
        {
            "number": "+14155552671",
            "max_pages": 8,
        },
        "scale",
    )
    assert pro.allowed is False
    assert "at most 6" in (pro.reason or "")
    assert scale.allowed is True


def test_caller_investigate_routing_keeps_same_quote() -> None:
    args = {
        "number": "+14155552671",
        "max_search_results": 10,
        "max_pages": 4,
    }
    direct = estimate_call("phone_caller_investigate", args, "pro")
    raw = estimate_call(
        "mesh_execute",
        {"ref": "callerintel:investigate", "arguments": args},
        "pro",
    )
    semantic = estimate_call(
        "mesh_capability_execute",
        {"capability": "phone.caller.investigate", "arguments": args},
        "pro",
    )
    assert direct.allowed is True
    assert raw.credits == direct.credits
    assert semantic.credits == direct.credits


def test_measured_caller_investigation_releases_unused_page_budget() -> None:
    settled = settle_measured_cost(
        "phone_caller_investigate",
        {
            "number": "+14155552671",
            "max_search_results": 10,
            "max_pages": 4,
        },
        "pro",
        reserved_credits=26,
        execution_usage={
            "counters": {
                "public_search_call": 1,
                "public_search_result": 3,
                "public_page_fetch": 2,
                "public_page_confirmed": 1,
            },
            "provider_calls": {
                "brave": 1,
                "nativeweb": 2,
                "callerintel": 1,
            },
        },
        latency_ms=1500,
    )
    assert settled == 19
