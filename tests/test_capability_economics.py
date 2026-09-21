from __future__ import annotations

from internet_hands.capability_economics import estimate_call, plan_privileges


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
