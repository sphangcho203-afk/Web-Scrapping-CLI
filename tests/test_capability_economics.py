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
    assert local.credits == 5
    assert firecrawl.credits == 252
    assert apify.credits == 1502


def test_semantic_fallback_reserves_all_eligible_attempts_and_settles_measured_work() -> None:
    args = {"capability": "web.fetch.page", "arguments": {"url": "https://example.com"}}
    free = estimate_call("mesh_capability_execute", args, "free")
    pro = estimate_call("mesh_capability_execute", args, "pro")
    assert free.allowed and free.credits >= 4
    assert pro.allowed and pro.credits >= 254
    assert settle_measured_cost(
        "mesh_capability_execute", args, "pro", reserved_credits=pro.credits,
        execution_usage={"provider_calls": {"firecrawl": 1, "nativeweb": 1},
                         "counters": {"firecrawl_work_units": 1}},
    ) == 256


def test_semantic_unknown_or_unbounded_work_is_not_one_credit() -> None:
    unknown = estimate_call("mesh_capability_execute", {"capability": "missing"}, "pro")
    assert unknown.allowed is False
    assert estimate_call("mesh_execute", {
        "ref": "firecrawl:crawl", "arguments": {"limit": 20},
    }, "pro").credits == 5002
    assert estimate_call("mesh_execute", {
        "ref": "firecrawl:crawl", "arguments": {"limit": 21},
    }, "pro").allowed is False
    assert estimate_call("mesh_execute", {
        "ref": "firecrawl:extract", "arguments": {"urls": ["https://example.com"]},
    }, "pro").allowed is False


def test_gaming_batches_reserve_each_operation_and_refund_unrun_work() -> None:
    args = {"requests": [
        {"capability": "mlbb.reference.heroes", "arguments": {}},
        {"capability": "mlbb.hero.list", "arguments": {}},
    ]}
    quote = estimate_call("gaming_intel", args, "pro")
    assert quote.credits >= 6
    assert settle_measured_cost(
        "gaming_intel", args, "pro", reserved_credits=quote.credits,
        execution_usage={"provider_calls": {"gamecore": 1}},
    ) == 4


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
    assert estimate.credits == 259


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
        reserved_credits=252,
        execution_usage={
            "counters": {"firecrawl_work_units": 1},
            "provider_calls": {"firecrawl": 1},
        },
        latency_ms=500,
    )
    assert settled == 252


def test_deep_caller_investigation_pricing_is_plan_bounded() -> None:
    builder = estimate_call("phone_caller_investigate", {"number": "+14155552671", "max_sources": 3}, "builder")
    assert builder.allowed is True
    assert builder.credits == 13
    too_deep = estimate_call("phone_caller_investigate", {"number": "+14155552671", "max_sources": 4}, "builder")
    assert too_deep.allowed is False
    assert "at most 3" in (too_deep.reason or "")


def test_deep_caller_investigation_measured_settlement_refunds_unused_fetches() -> None:
    settled = settle_measured_cost("phone_caller_investigate", {"number": "+14155552671", "max_sources": 3}, "builder", reserved_credits=13, execution_usage={"counters": {"public_search_call": 1, "public_search_result": 4, "caller_source_fetch": 1}, "provider_calls": {"nativeweb": 1}})
    assert settled == 12


def test_deep_caller_investigation_measured_settlement_survives_raw_mesh_route() -> None:
    settled = settle_measured_cost("mesh_execute", {"ref": "callerresearch:investigate", "arguments": {"number": "+14155552671", "max_sources": 3}}, "builder", reserved_credits=13, execution_usage={"counters": {"public_search_call": 1, "public_search_result": 4, "caller_source_fetch": 1}, "provider_calls": {"callerresearch": 1, "nativeweb": 1}})
    assert settled == 12


def test_deep_caller_investigation_measured_settlement_survives_semantic_route() -> None:
    settled = settle_measured_cost("mesh_capability_execute", {"capability": "phone.caller.investigate", "arguments": {"number": "+14155552671", "max_sources": 3}}, "builder", reserved_credits=13, execution_usage={"counters": {"public_search_call": 1, "public_search_result": 4, "caller_source_fetch": 1}, "provider_calls": {"callerresearch": 1, "nativeweb": 1}})
    assert settled == 12



def test_connected_app_execution_is_free_on_every_plan() -> None:
    for plan in ("free", "builder", "pro", "scale"):
        quote = estimate_call(
            "mesh_execute",
            {
                "ref": "composio:GMAIL_SEND_EMAIL",
                "arguments": {"to": "person@example.com", "subject": "Hello"},
                "account": "ca_user_owned",
            },
            plan,
        )
        assert quote.allowed is True
        assert quote.credits == 0
        assert quote.category == "byo_external"
        assert quote.minimum_plan == "free"
        assert settle_measured_cost(
            "mesh_execute",
            {
                "ref": "composio:GMAIL_SEND_EMAIL",
                "arguments": {"to": "person@example.com", "subject": "Hello"},
                "account": "ca_user_owned",
            },
            plan,
            reserved_credits=quote.credits,
            execution_usage={"provider_calls": {"composio": 1}},
        ) == 0


def test_user_saved_remote_mcp_is_free_but_operator_mcp_can_still_be_metered() -> None:
    user_owned = estimate_call(
        "mesh_execute",
        {
            "ref": "mcp:con_0123456789abcdef::SEARCH",
            "arguments": {"query": "example"},
        },
        "free",
    )
    operator_route = estimate_call(
        "mesh_execute",
        {
            "ref": "mcp:company_search::SEARCH",
            "arguments": {"query": "example"},
        },
        "free",
    )

    assert user_owned.allowed is True
    assert user_owned.credits == 0
    assert user_owned.category == "byo_external"

    assert operator_route.allowed is True
    assert operator_route.credits == 4


def test_pure_byo_batch_has_zero_wallet_charge() -> None:
    args = {
        "calls": [
            {
                "ref": "composio:GITHUB_CREATE_ISSUE",
                "arguments": {"title": "Bug"},
                "account": "ca_github",
            },
            {
                "ref": "mcp:con_abcdef::NOTION_SEARCH",
                "arguments": {"query": "roadmap"},
            },
        ]
    }
    quote = estimate_call("mesh_batch_execute", args, "free")
    assert quote.allowed is True
    assert quote.credits == 0
    assert settle_measured_cost(
        "mesh_batch_execute",
        args,
        "free",
        reserved_credits=quote.credits,
        execution_usage={"provider_calls": {"composio": 1, "mcp": 1}},
    ) == 0


def test_mixed_batch_only_charges_opencrawl_supplied_work() -> None:
    args = {
        "calls": [
            {
                "ref": "composio:GMAIL_SEARCH_EMAILS",
                "arguments": {"query": "invoice"},
                "account": "ca_mail",
            },
            {
                "ref": "nativeweb:fetch",
                "arguments": {"url": "https://example.com"},
            },
        ]
    }
    quote = estimate_call("mesh_batch_execute", args, "free")

    assert quote.allowed is True
    assert quote.credits == 7
    assert settle_measured_cost(
        "mesh_batch_execute",
        args,
        "free",
        reserved_credits=quote.credits,
        execution_usage={
            "provider_calls": {"composio": 1, "nativeweb": 1},
            "counters": {"native_web_requests": 1},
        },
    ) == 7


def test_semantic_connected_capability_does_not_add_orchestration_fee() -> None:
    args = {
        "capability": "messaging.send",
        "arguments": {
            "platform": "telegram",
            "target": "12345",
            "message": "hello",
        },
    }
    quote = estimate_call("mesh_capability_execute", args, "free")

    assert quote.allowed is True
    assert quote.credits == 0
    assert settle_measured_cost(
        "mesh_capability_execute",
        args,
        "free",
        reserved_credits=quote.credits,
        execution_usage={"provider_calls": {"composio": 1}},
    ) == 0



def test_byo_batch_is_free_but_still_obeys_plan_batch_limit() -> None:
    args = {
        "calls": [
            {
                "ref": f"composio:TOOL_{index}",
                "arguments": {},
                "account": "ca_owned",
            }
            for index in range(4)
        ]
    }
    quote = estimate_call("mesh_batch_execute", args, "free")
    assert quote.allowed is False
    assert "at most 3" in (quote.reason or "")



def test_first_party_intelligence_reserves_browser_fallback_headroom() -> None:
    no_render = estimate_call(
        "mesh_execute",
        {
            "ref": "intelligence:smart-fetch",
            "arguments": {"url": "https://example.com", "render": "never"},
        },
        "free",
    )
    auto = estimate_call(
        "mesh_execute",
        {
            "ref": "intelligence:smart-fetch",
            "arguments": {"url": "https://example.com", "render": "auto"},
        },
        "free",
    )
    assert no_render.allowed and no_render.credits == 5
    assert auto.allowed and auto.credits == 11


def test_first_party_intelligence_settles_only_work_actually_attempted() -> None:
    args = {
        "ref": "intelligence:smart-fetch",
        "arguments": {"url": "https://example.com", "render": "auto"},
    }
    reserved = estimate_call("mesh_execute", args, "free").credits
    assert reserved == 11
    assert settle_measured_cost(
        "mesh_execute",
        args,
        "free",
        reserved_credits=reserved,
        execution_usage={
            "provider_calls": {"intelligence": 1},
            "counters": {"intelligence_http_requests": 1},
        },
    ) == 5
    assert settle_measured_cost(
        "mesh_execute",
        args,
        "free",
        reserved_credits=reserved,
        execution_usage={
            "provider_calls": {"intelligence": 1},
            "counters": {
                "intelligence_http_requests": 1,
                "intelligence_browser_renders": 1,
            },
        },
    ) == 11


def test_search_extract_reservation_is_bounded_by_requested_result_count() -> None:
    quote = estimate_call(
        "mesh_execute",
        {
            "ref": "intelligence:search-extract",
            "arguments": {"query": "latest ai research", "count": 2},
        },
        "free",
    )
    assert quote.allowed is True
    assert quote.credits == 28



def test_tavily_reservation_tracks_requested_upstream_work() -> None:
    basic = estimate_call(
        "mesh_execute",
        {
            "ref": "tavily:search",
            "arguments": {"query": "agent systems", "search_depth": "basic"},
        },
        "pro",
    )
    advanced = estimate_call(
        "mesh_execute",
        {
            "ref": "tavily:search",
            "arguments": {"query": "agent systems", "search_depth": "advanced"},
        },
        "pro",
    )
    extract = estimate_call(
        "mesh_execute",
        {
            "ref": "tavily:extract",
            "arguments": {
                "urls": [f"https://example.com/{index}" for index in range(10)],
                "extract_depth": "basic",
            },
        },
        "pro",
    )
    mapped = estimate_call(
        "mesh_execute",
        {
            "ref": "tavily:map",
            "arguments": {"url": "https://example.com", "limit": 20},
        },
        "pro",
    )
    crawl = estimate_call(
        "mesh_execute",
        {
            "ref": "tavily:crawl",
            "arguments": {
                "url": "https://example.com",
                "limit": 20,
                "extract_depth": "advanced",
            },
        },
        "pro",
    )

    assert basic.allowed is True and basic.credits == 42
    assert advanced.allowed is True and advanced.credits == 82
    assert extract.allowed is True and extract.credits == 82
    assert mapped.allowed is True and mapped.credits == 82
    # map: 2 upstream credits; advanced extraction: 8 upstream credits.
    assert crawl.allowed is True and crawl.credits == 402


def test_tavily_measured_settlement_uses_reported_api_credits() -> None:
    args = {
        "ref": "tavily:search",
        "arguments": {"query": "agent systems", "search_depth": "advanced"},
    }
    quote = estimate_call("mesh_execute", args, "pro")
    assert quote.credits == 82
    assert settle_measured_cost(
        "mesh_execute",
        args,
        "pro",
        reserved_credits=quote.credits,
        execution_usage={
            "provider_calls": {"tavily": 1},
            "counters": {"tavily_credits": 1},
        },
    ) == 42


def test_exa_reserves_headroom_and_settles_from_reported_dollars() -> None:
    args = {
        "ref": "exa:search",
        "arguments": {"query": "agent systems", "numResults": 25},
    }
    quote = estimate_call("mesh_execute", args, "pro")
    assert quote.allowed is True
    assert quote.credits == 502

    # $0.007 == 7,000 micro-USD; at 5,000 wallet units/USD that is 35 units.
    assert settle_measured_cost(
        "mesh_execute",
        args,
        "pro",
        reserved_credits=quote.credits,
        execution_usage={
            "provider_calls": {"exa": 1},
            "counters": {"exa_cost_microusd": 7000},
        },
    ) == 37


def test_provider_work_bounds_reject_unquotable_fanout() -> None:
    tavily = estimate_call(
        "mesh_execute",
        {
            "ref": "tavily:extract",
            "arguments": {
                "urls": [f"https://example.com/{index}" for index in range(21)],
            },
        },
        "pro",
    )
    exa = estimate_call(
        "mesh_execute",
        {
            "ref": "exa:contents",
            "arguments": {
                "urls": [f"https://example.com/{index}" for index in range(21)],
            },
        },
        "pro",
    )

    assert tavily.allowed is False
    assert "1 to 20" in (tavily.reason or "")
    assert exa.allowed is False
    assert "1 to 20" in (exa.reason or "")
