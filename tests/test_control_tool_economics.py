from __future__ import annotations

import pytest

from internet_hands.control_store import AuthIdentity, ControlError, ControlStore


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

    assert local["credits"] == 2
    assert enriched["credits"] == 6
    assert enriched["category"] == "phone_intelligence"
    assert len(enriched["breakdown"]) == 3


def test_control_store_allows_paid_provider_with_wallet_charge() -> None:
    store = ControlStore(dsn=None)

    quote = store.quote_tool_call(
        identity=_identity("builder"),
        tool_name="phone_number_lookup",
        arguments={
            "number": "+14155552671",
            "external": True,
            "providers": ["twilio"],
        },
    )

    assert quote["credits"] == 10
    assert quote["provider_class"] == "metered"


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
    assert quote["credits"] == 6
    assert quote["provider_class"] == "public"
    assert quote["retry_reservation"] == {
        "attempts": 2,
        "retries": 1,
        "quoted_once": 3,
        "reserved": 6,
    }


def test_free_plan_cannot_route_around_paid_provider_gate() -> None:
    store = ControlStore(dsn=None)
    with pytest.raises(ControlError) as exc:
        store.quote_tool_call(
            identity=_identity("free"),
            tool_name="mesh_execute",
            arguments={
                "ref": "apify:actor",
                "arguments": {"query": "example"},
            },
        )
    assert exc.value.code == "plan_restricted"


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
    assert quote["credits"] == 20
    assert quote["category"] == "phone_intelligence"
    assert quote["retry_reservation"]["quoted_once"] == 10



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

    assert quote["credits"] == 3
    assert "retry_reservation" not in quote
