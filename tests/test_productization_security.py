from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from internet_hands import control_api, security_api
from internet_hands.control_store import AuthIdentity, ControlError, ControlStore


class _Request:
    def __init__(self, body: dict | None = None, *, cookies: dict | None = None) -> None:
        self._body = body or {}
        self.cookies = cookies or {}
        self.headers = {"host": "example.test", "x-forwarded-proto": "https"}
        self.url = SimpleNamespace(scheme="https", netloc="example.test")

    async def json(self) -> dict:
        return self._body

    async def body(self) -> bytes:
        return b""


@pytest.mark.asyncio
async def test_signup_enters_dedicated_verification_flow(monkeypatch) -> None:
    created = {"id": "usr_pending"}
    user = {
        "id": "usr_pending",
        "email": "pending@example.test",
        "display_name": "Pending",
        "email_verified": False,
        "created_at": datetime(2026, 9, 14, tzinfo=UTC),
    }
    monkeypatch.setattr(security_api.store, "create_user", lambda **_kwargs: created)
    monkeypatch.setattr(security_api.store, "get_user", lambda _user_id: user)
    monkeypatch.setattr(security_api.store, "create_session", lambda **_kwargs: None)

    async def sent(_request, _user):
        return True

    monkeypatch.setattr(security_api, "_send_verification", sent)
    response = await security_api.signup_secure(
        _Request({"email": user["email"], "password": "long-enough-password"})
    )
    payload = json.loads(response.body)

    assert response.status_code == 202
    assert payload["verification_required"] is True
    assert payload["next"] == "/verify-email"
    assert payload["resumed"] is False
    assert "ih_session=" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_signup_resumes_matching_unverified_account_after_interrupted_response(
    monkeypatch,
) -> None:
    password = "long-enough-password"
    private = {
        "id": "usr_pending",
        "email": "pending@example.test",
        "password_hash": security_api.hash_password(password),
        "email_verified": False,
    }
    public = {
        "id": "usr_pending",
        "email": "pending@example.test",
        "display_name": "Pending",
        "email_verified": False,
        "created_at": datetime(2026, 9, 14, tzinfo=UTC),
    }

    def duplicate(**_kwargs):
        raise ControlError("email_in_use", "an account with this email already exists", 409)

    monkeypatch.setattr(security_api.store, "create_user", duplicate)
    monkeypatch.setattr(security_api.store, "get_user_by_email", lambda _email: private)
    monkeypatch.setattr(security_api.store, "get_user", lambda _user_id: public)
    monkeypatch.setattr(security_api.store, "create_session", lambda **_kwargs: None)

    async def sent(_request, _user):
        return True

    monkeypatch.setattr(security_api, "_send_verification", sent)
    response = await security_api.signup_secure(
        _Request({"email": private["email"], "password": password})
    )
    payload = json.loads(response.body)

    assert response.status_code == 202
    assert payload["resumed"] is True
    assert payload["verification_required"] is True
    assert payload["next"] == "/verify-email"
    assert "ih_session=" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_verification_setup_failure_does_not_strand_signup_response(monkeypatch) -> None:
    def fail_verification(**_kwargs):
        raise RuntimeError("verification storage unavailable")

    monkeypatch.setattr(
        security_api.security, "create_email_verification", fail_verification
    )

    sent = await security_api._send_verification(
        _Request(),
        {"id": "usr_pending", "email": "pending@example.test"},
    )

    assert sent is False


@pytest.mark.asyncio
async def test_mail_configuration_failure_is_logged_without_recipient(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        security_api.security,
        "claim_email_event",
        lambda **_kwargs: "evt_1",
    )
    monkeypatch.setattr(
        security_api.security,
        "finish_email_event",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(security_api, "mail_provider", lambda: None)

    async def fail_mail(**_kwargs):
        raise security_api.MailError("transactional email is not configured")

    monkeypatch.setattr(security_api, "send_mail", fail_mail)

    with caplog.at_level("WARNING"):
        sent = await security_api._deliver(
            user_id="usr_pending",
            email="private@example.test",
            event_type="email_verification",
            subject="Verify",
            text="Verify",
            body_html="<p>Verify</p>",
        )

    assert sent is False
    assert caplog.records[-1].failure_reason == "not_configured"
    assert caplog.records[-1].mail_provider == "none"
    assert "private@example.test" not in caplog.text


@pytest.mark.asyncio
async def test_unverified_password_login_returns_verification_next_step(monkeypatch) -> None:
    private = {
        "id": "usr_pending",
        "email": "pending@example.test",
        "password_hash": security_api.hash_password("long-enough-password"),
    }
    public = {
        "id": "usr_pending",
        "email": "pending@example.test",
        "email_verified": False,
        "created_at": datetime(2026, 9, 14, tzinfo=UTC),
    }
    monkeypatch.setattr(security_api.store, "get_user_by_email", lambda _email: private)
    monkeypatch.setattr(security_api.store, "get_user", lambda _user_id: public)
    monkeypatch.setattr(security_api.store, "create_session", lambda **_kwargs: None)
    monkeypatch.setattr(
        security_api.security,
        "account_security",
        lambda _user_id: {"totp_enabled": False, "email_verified": False},
    )

    async def send_verification(_request, _user):
        return True

    async def notice(*_args):
        return None

    monkeypatch.setattr(security_api, "_send_verification", send_verification)
    monkeypatch.setattr(security_api, "_send_login_notice", notice)
    response = await security_api.login_secure(
        _Request({"email": private["email"], "password": "long-enough-password"})
    )
    payload = json.loads(response.body)

    assert payload["verification_required"] is True
    assert payload["verification_sent"] is True
    assert payload["verification_context"] == "signin"
    assert payload["next"] == "/verify-email"


@pytest.mark.asyncio
async def test_unverified_password_login_reports_delivery_failure(monkeypatch) -> None:
    password = "long-enough-password"
    private = {
        "id": "usr_pending",
        "email": "pending@example.test",
        "password_hash": security_api.hash_password(password),
    }
    public = {
        "id": "usr_pending",
        "email": "pending@example.test",
        "email_verified": False,
    }
    monkeypatch.setattr(security_api.store, "get_user_by_email", lambda _email: private)
    monkeypatch.setattr(security_api.store, "get_user", lambda _user_id: public)
    monkeypatch.setattr(security_api.store, "create_session", lambda **_kwargs: None)
    monkeypatch.setattr(
        security_api.security,
        "account_security",
        lambda _user_id: {"totp_enabled": False, "email_verified": False},
    )

    async def fail_delivery(_request, _user):
        return False

    monkeypatch.setattr(security_api, "_send_verification", fail_delivery)
    response = await security_api.login_secure(
        _Request({"email": private["email"], "password": password})
    )
    payload = json.loads(response.body)

    assert payload["verification_required"] is True
    assert payload["verification_sent"] is False
    assert payload["verification_context"] == "signin"


def test_unverified_accounts_fail_closed_at_privileged_guard() -> None:
    with pytest.raises(HTTPException) as exc:
        control_api._require_verified({"id": "usr_pending", "email_verified": False})
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "email_verification_required"


def test_security_status_does_not_expose_mail_provider(monkeypatch) -> None:
    monkeypatch.setattr(security_api, "_require_user", lambda _request: {"id": "usr_1"})
    monkeypatch.setattr(
        security_api.security,
        "account_security",
        lambda _user_id: {"email_verified": True, "totp_enabled": False},
    )
    monkeypatch.setattr(security_api, "encryption_configured", lambda: True)
    monkeypatch.setattr(security_api, "mail_provider", lambda: "smtp")

    payload = security_api.security_status(object())

    assert payload["transactional_mail_configured"] is True
    assert "mail_provider" not in payload


def test_totp_setup_includes_offline_scannable_qr(monkeypatch) -> None:
    monkeypatch.setattr(
        security_api,
        "_require_user",
        lambda _request: {
            "id": "usr_1",
            "email": "user@example.test",
            "email_verified": True,
        },
    )
    monkeypatch.setattr(
        security_api.security,
        "account_security",
        lambda _user_id: {"email_verified": True},
    )
    monkeypatch.setattr(security_api, "encryption_configured", lambda: True)
    monkeypatch.setattr(security_api.security, "put_pending_totp", lambda *_args: None)
    monkeypatch.setattr(security_api, "encrypt_secret", lambda value: f"encrypted:{value}")

    payload = security_api.two_factor_setup(object())

    assert payload["otpauth_uri"].startswith("otpauth://totp/")
    assert payload["qr_data_uri"].startswith("data:image/svg+xml;base64,")


@pytest.mark.asyncio
async def test_oauth_approval_rejects_unverified_api_key_owner(monkeypatch) -> None:
    identity = AuthIdentity(
        user_id="usr_pending",
        api_key_id="key_1",
        scopes=["*"],
        plan_slug="free",
        rpm_limit=10,
        source="api_key",
    )
    monkeypatch.setattr(control_api, "_parse_form", lambda _raw: {
        "client_id": "client",
        "redirect_uri": "https://client.example/callback",
        "code_challenge": "challenge",
        "api_key": "ih_live_secret",
    })
    monkeypatch.setattr(control_api, "authenticate_secret", lambda *_args: identity)
    monkeypatch.setattr(
        control_api.store,
        "get_user",
        lambda _user_id: {"id": "usr_pending", "email_verified": False},
    )

    with pytest.raises(HTTPException) as exc:
        await control_api.oauth_authorize_submit(_Request())
    assert exc.value.status_code == 403


class _Cursor:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query: str, _params=None) -> None:
        self.queries.append(" ".join(query.split()))

    def fetchone(self):
        return {"id": "rst_1", "user_id": "usr_1"}


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self) -> _Cursor:
        return self._cursor

    def commit(self) -> None:
        self.committed = True


def test_password_reset_revokes_existing_web_sessions_atomically(monkeypatch) -> None:
    cursor = _Cursor()
    connection = _Connection(cursor)
    store = ControlStore.__new__(ControlStore)
    monkeypatch.setattr(store, "ensure_schema", lambda: None)
    monkeypatch.setattr(store, "_connect", lambda: connection)

    assert store.consume_password_reset("reset-hash", "password-hash") is True
    assert any("DELETE FROM ih_sessions WHERE user_id=%s" in query for query in cursor.queries)
    assert connection.committed is True
