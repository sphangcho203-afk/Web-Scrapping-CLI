from __future__ import annotations

from fastapi import HTTPException
from starlette.requests import Request

import internet_hands.playground_api as playground
from internet_hands.control_store import AuthIdentity


def _request(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/playground/run", "headers": headers})


def _identity(api_key_id: str | None = "key_1", scopes: list[str] | None = None) -> AuthIdentity:
    return AuthIdentity(
        user_id="usr_test",
        api_key_id=api_key_id,
        scopes=scopes or ["mcp:execute"],
        plan_slug="free",
        rpm_limit=10,
        source="api_key",
    )


def test_playground_accepts_bearer_identity_without_dashboard_session(monkeypatch) -> None:
    monkeypatch.setattr(playground, "authenticate_secret", lambda store, secret: _identity())
    identity = playground._playground_identity(
        _request([(b"authorization", b"Bearer ih_live_test")]),
        {"operation": "research"},
    )
    assert identity.user_id == "usr_test"
    assert identity.api_key_id == "key_1"


def test_playground_accepts_x_api_key_identity(monkeypatch) -> None:
    monkeypatch.setattr(playground, "authenticate_secret", lambda store, secret: _identity())
    identity = playground._playground_identity(
        _request([(b"x-api-key", b"ih_live_test")]),
        {"operation": "search"},
    )
    assert identity.source == "api_key"


def test_playground_rejects_mismatched_selected_key(monkeypatch) -> None:
    monkeypatch.setattr(playground, "authenticate_secret", lambda store, secret: _identity("key_1"))
    try:
        playground._playground_identity(
            _request([(b"authorization", b"Bearer ih_live_test")]),
            {"api_key_id": "key_2"},
        )
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail["code"] == "credential_mismatch"
    else:
        raise AssertionError("expected credential mismatch")


def test_playground_bearer_requires_execute_scope(monkeypatch) -> None:
    monkeypatch.setattr(playground, "authenticate_secret", lambda store, secret: _identity(scopes=["account:read"]))
    try:
        playground._playground_identity(
            _request([(b"authorization", b"Bearer ih_live_test")]),
            {},
        )
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail["code"] == "scope_required"
    else:
        raise AssertionError("expected scope error")
