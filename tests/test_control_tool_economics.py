from __future__ import annotations

import pytest

from internet_hands.capability_economics import estimate_call, settle_measured_cost
from internet_hands.control_store import (
    AuthIdentity,
    ControlStore,
    raw_credits_from_wallet_reservation,
    wallet_credits_for_raw,
)


def _identity(plan: str) -> AuthIdentity:
    return AuthIdentity(
        user_id="usr_test",
        api_key_id="key_test",
        scopes=["mcp:read", "mcp:execute"],
        plan_slug=plan,
        rpm_limit=100,
        source="api_key",
    )


def test_control_store_quotes_variable_phone_costs_without_database() -> None:
    store = ControlStore(dsn=None)

    local = store.quote_tool_call(
        identity=_identity("free"),
        tool_name="phone_number_lookup",
        arguments={"number": "+14155552671", "external": False},
    )
    enriched = store.quote_tool_call(
        identity=_identity("builder"),
        tool_name="phone_number_lookup",
        arguments={
            "number": "+14155552671",
            "external": True,
            "providers": ["veriphone", "abstract"],
        },
    )

    assert local["credits"] == 6
    assert local["raw_credits"] == 2
    assert enriched["credits"] == 18
    assert enriched["raw_credits"] == 6
    assert enriched["credit_burn_multiplier"] == 3
    assert enriched["category"] == "phone_intelligence"
    assert len(enriched["breakdown"]) == 4


def test_control_store_allows_metered_provider_on_lower_plan_when_wallet_can_pay() -> None:
    store = ControlStore(dsn=None)

    quote = store.quote_tool_call(
        identity=_identity("free"),
        tool_name="phone_number_lookup",
        arguments={
            "number": "+14155552671",
            "external": True,
            "providers": ["twilio"],
        },
    )

    assert quote["provider_class"] == "metered"
    assert quote["raw_credits"] == 10
    assert quote["credits"] == 30


def test_free_plan_still_has_real_public_tool_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_READ_RETRIES", "1")
    store = ControlStore(dsn=None)
    quote = store.quote_tool_call(
        identity=_identity("free"),
        tool_name="mesh_execute",
        arguments={
            "ref": "publicapi:lookup",
            "arguments": {"query": "example"},
        },
    )
    assert quote["credits"] == 18
    assert quote["raw_credits"] == 6
    assert quote["provider_class"] == "public"
    assert quote["retry_reservation"] == {
        "attempts": 2,
        "retries": 1,
        "quoted_once": 9,
        "retryable_once": 9,
        "reserved": 18,
        "credit_burn_multiplier": 3,
    }


def test_free_plan_can_use_paid_provider_when_it_has_credits() -> None:
    store = ControlStore(dsn=None)
    quote = store.quote_tool_call(
        identity=_identity("free"),
        tool_name="mesh_execute",
        arguments={
            "ref": "apify:actor",
            "arguments": {"query": "example"},
        },
    )
    assert quote["provider_class"] == "metered"
    assert quote["raw_credits"] == 1502
    assert quote["credits"] == 4506


def test_nested_phone_mesh_route_gets_phone_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_READ_RETRIES", "1")
    store = ControlStore(dsn=None)
    quote = store.quote_tool_call(
        identity=_identity("pro"),
        tool_name="mesh_execute",
        arguments={
            "ref": "phoneintel:lookup",
            "arguments": {
                "number": "+14155552671",
                "external": True,
                "providers": ["twilio"],
            },
        },
    )
    assert quote["credits"] == 60
    assert quote["raw_credits"] == 20
    assert quote["category"] == "phone_intelligence"
    assert quote["retry_reservation"]["quoted_once"] == 30



def test_byo_connected_tool_stays_zero_with_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_READ_RETRIES", "3")
    store = ControlStore(dsn=None)

    quote = store.quote_tool_call(
        identity=_identity("free"),
        tool_name="mesh_execute",
        arguments={
            "ref": "composio:GMAIL_SEARCH_EMAILS",
            "arguments": {"query": "invoice"},
            "account": "ca_mail",
        },
    )

    assert quote["credits"] == 0
    assert "retry_reservation" not in quote


def test_disabling_read_retries_removes_retry_headroom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_READ_RETRIES", "0")
    store = ControlStore(dsn=None)

    quote = store.quote_tool_call(
        identity=_identity("free"),
        tool_name="mesh_execute",
        arguments={
            "ref": "publicapi:lookup",
            "arguments": {"query": "example"},
        },
    )

    assert quote["credits"] == 9
    assert quote["raw_credits"] == 3
    assert "retry_reservation" not in quote


def test_credit_burn_multiplier_is_operator_tunable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_READ_RETRIES", "0")
    monkeypatch.setenv("OPENCRAWL_CREDIT_BURN_MULTIPLIER", "4")
    store = ControlStore(dsn=None)

    quote = store.quote_tool_call(
        identity=_identity("free"),
        tool_name="mesh_execute",
        arguments={
            "ref": "publicapi:lookup",
            "arguments": {"query": "example"},
        },
    )

    assert quote["raw_credits"] == 3
    assert quote["credit_burn_multiplier"] == 4
    assert quote["credits"] == 12




def test_unmeasured_fallback_is_not_burned_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_READ_RETRIES", "0")
    monkeypatch.setenv("OPENCRAWL_CREDIT_BURN_MULTIPLIER", "3")
    store = ControlStore(dsn=None)
    arguments = {"query": "example"}

    quote = store.quote_tool_call(
        identity=_identity("free"),
        tool_name="mesh_search",
        arguments=arguments,
    )
    assert quote["raw_credits"] == 1
    assert quote["credits"] == 3

    raw_reserved = raw_credits_from_wallet_reservation(quote["credits"])
    raw_actual = settle_measured_cost(
        "mesh_search",
        arguments,
        "free",
        reserved_credits=raw_reserved,
        execution_usage={},
    )
    assert raw_reserved == 1
    assert raw_actual == 1
    assert wallet_credits_for_raw(raw_actual) == 3

def test_side_effecting_raw_mesh_routes_do_not_reserve_retry_headroom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_READ_RETRIES", "3")
    store = ControlStore(dsn=None)
    quotes = [
        store.quote_tool_call(
            identity=_identity("pro"),
            tool_name="mesh_execute",
            arguments={"ref": "apify:owner/actor", "arguments": {"url": "https://example.com"}},
        ),
        store.quote_tool_call(
            identity=_identity("pro"),
            tool_name="mesh_execute",
            arguments={"ref": "nativesandbox:exec", "arguments": {"command": "echo hi"}},
        ),
        store.quote_tool_call(
            identity=_identity("pro"),
            tool_name="mesh_execute",
            arguments={"ref": "firecrawl:interact", "arguments": {"prompt": "click next"}},
        ),
    ]
    assert all("retry_reservation" not in quote for quote in quotes)


def test_batch_retry_headroom_excludes_side_effecting_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_READ_RETRIES", "1")
    store = ControlStore(dsn=None)
    calls = [
        {"ref": "publicapi:lookup", "arguments": {"query": "example"}},
        {"ref": "nativesandbox:exec", "arguments": {"command": "echo hi"}},
    ]
    base = estimate_call("mesh_batch_execute", {"calls": calls}, "pro")
    quote = store.quote_tool_call(
        identity=_identity("pro"),
        tool_name="mesh_batch_execute",
        arguments={"calls": calls},
    )
    retryable = estimate_call("mesh_execute", calls[0], "pro").credits
    assert quote["raw_credits"] == base.credits + retryable
    assert quote["credits"] == (base.credits + retryable) * 3
    assert quote["retry_reservation"]["retryable_once"] == retryable * 3
