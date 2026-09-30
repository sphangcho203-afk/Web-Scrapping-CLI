from __future__ import annotations

import pytest

from internet_hands.capability_economics import estimate_call, settle_measured_cost
from internet_hands.control_store import AuthIdentity, ControlError, ControlStore

IDENTITY = AuthIdentity("owner", None, ["mcp:execute"], "free", 100, "session", 10)


def test_quote_revision_binds_owner_inputs_and_pricing(monkeypatch):
    monkeypatch.setenv("OPENCRAWL_CREDIT_BURN_MULTIPLIER", "3")
    store = ControlStore("unused")
    quote = store.quote_tool_call(identity=IDENTITY, tool_name="playground:crawl", arguments={"max_pages": 2})
    assert len(quote["quote_revision"]) == 64
    same = store.quote_tool_call(identity=IDENTITY, tool_name="playground:crawl",
                                arguments={"max_pages": 2, "max_charge_credits": 100})
    assert same["quote_revision"] == quote["quote_revision"]
    changed = store.quote_tool_call(identity=IDENTITY, tool_name="playground:crawl", arguments={"max_pages": 3})
    assert changed["quote_revision"] != quote["quote_revision"]
    monkeypatch.setenv("OPENCRAWL_CREDIT_BURN_MULTIPLIER", "7")
    updated = store.quote_tool_call(identity=IDENTITY, tool_name="playground:crawl", arguments={"max_pages": 2})
    assert updated["quote_revision"] != quote["quote_revision"]


@pytest.mark.parametrize("limit", [True, -1, 0.5, "5", None, 1000000001])
def test_invalid_spend_caps_fail_before_database_access(limit):
    store = ControlStore("unused")
    with pytest.raises(ControlError, match="max_charge_credits"):
        store.reserve_tool_call(identity=IDENTITY, request_id="unstarted", tool_name="playground:crawl",
                                arguments={"max_charge_credits": limit}, input_bytes=0)


def test_under_budget_request_cannot_reserve_or_execute():
    store = ControlStore("unused")
    with pytest.raises(ControlError, match="spending limit"):
        store.reserve_tool_call(identity=IDENTITY, request_id="unstarted", tool_name="playground:crawl",
                                arguments={"max_charge_credits": 0}, input_bytes=0)


def test_paid_recovery_has_explicit_bounded_headroom():
    native = estimate_call("playground:research", {"query": "example", "max_pages": 4, "paid_recovery": False}, "free")
    paid_args = {"query": "example", "max_pages": 4, "paid_recovery": True}
    paid = estimate_call("playground:research", paid_args, "free")
    assert native.credits == 3
    assert paid.credits == 1253
    measured = {"completed": True, "provider_usage": [
        {"provider": "firecrawl", "operation": "search", "credits_used": 2},
        {"provider": "firecrawl", "operation": "scrape", "credits_used": 1},
    ]}
    assert settle_measured_cost("playground:research", paid_args, "free",
                               reserved_credits=paid.credits, execution_usage=measured) == 751


def test_paid_basic_operation_units_are_disclosed_when_upstream_does_not_report_cost():
    args = {"query": "example", "paid_recovery": True}
    charge = settle_measured_cost("playground:research", args, "free", reserved_credits=1253,
        execution_usage={"completed": True, "provider_usage": [
            {"provider": "firecrawl", "operation": "search", "credits_used": None, "policy_work_units": 2, "status": "ok"},
            {"provider": "firecrawl", "operation": "scrape", "credits_used": None, "policy_work_units": 1, "status": "error"},
        ]})
    assert charge == 501
