from __future__ import annotations

from internet_hands.capability_economics import estimate_call, settle_measured_cost


def test_research_reserves_bounded_search_and_recovery_then_releases_unused_credits() -> None:
    args = {"query": "latest AI news"}
    reserved = estimate_call("playground:research", args, "free").credits
    assert reserved == 6
    measured = {"completed": True, "provider_usage": [
        {"provider": "firecrawl", "operation": "search", "credits_used": 2},
        {"provider": "firecrawl", "operation": "scrape", "credits_used": 1},
        {"provider": "firecrawl", "operation": "scrape", "credits_used": None},
    ]}
    assert settle_measured_cost("playground:research", args, "free", reserved_credits=reserved, execution_usage=measured) == 4


def test_provider_overage_cannot_exceed_customer_reservation() -> None:
    args = {"query": "latest AI news"}
    reserved = estimate_call("playground:search", args, "free").credits
    assert reserved == 3
    assert settle_measured_cost(
        "playground:search", args, "free", reserved_credits=reserved,
        execution_usage={"completed": True, "provider_usage": [{"credits_used": 212}]},
    ) == reserved


def test_failed_request_releases_base_if_no_provider_credits_were_reported() -> None:
    args = {"query": "latest AI news"}
    assert settle_measured_cost(
        "playground:search", args, "free", reserved_credits=3,
        execution_usage={"completed": False, "provider_usage": [{"credits_used": None}]},
    ) == 0
