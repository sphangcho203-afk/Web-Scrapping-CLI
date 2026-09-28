from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from internet_hands import control_api, security_api, security_hardening
from internet_hands.control_store import ControlStore


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
    user = {
        "id": "usr_pending",
        "email": "pending@example.test",
        "display_name": "Pending",
        "email_verified": False,
        "created_at": datetime(2026, 9, 14, tzinfo=UTC),
    }

    async def signup(**kwargs):
        assert kwargs["email_confirm"] is False
        return {
            "user": {
                "id": "auth_pending",
                "email": user["email"],
                "identities": [{"id": "identity_1"}],
            },
            "session": None,
        }

    monkeypatch.setattr(security_api, "supabase_admin_create_user", signup)
    async def send_verification(*_args):
        return True
    monkeypatch.setattr(security_api, "_send_verification", send_verification)

    def ensure_auth_user(**kwargs):
        assert kwargs["provider"] == "supabase"
        assert kwargs["subject"] == "auth_pending"
        assert kwargs["email"] == user["email"]
        return user

    monkeypatch.setattr(security_api.store, "ensure_auth_user", ensure_auth_user)
    monkeypatch.setattr(security_api.store, "create_session", lambda **_kwargs: None)

    response = await security_api.signup_secure(
        _Request({"email": user["email"], "password": "long-enough-password"})
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["verification_required"] is True
    assert payload["verification_sent"] is True
    assert payload["verification_mode"] == "link_or_code"
    assert payload["next"] == "/verify-email"
    assert "ih_session=" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_signup_rejects_existing_supabase_identity(monkeypatch) -> None:
    async def duplicate(**_kwargs):
        raise security_api.SupabaseAuthError("User already registered", status_code=422)

    monkeypatch.setattr(security_api, "supabase_admin_create_user", duplicate)

    with pytest.raises(HTTPException) as exc:
        await security_api.signup_secure(
            _Request(
                {
                    "email": "pending@example.test",
                    "password": "long-enough-password",
                }
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "email_in_use"


@pytest.mark.asyncio
async def test_verification_keeps_local_challenge_when_identity_sync_fails(monkeypatch) -> None:
    user = {"id": "usr_pending", "email": "pending@example.test", "email_verified": False}
    monkeypatch.setattr(security_api, "_require_user", lambda _request: user)
    monkeypatch.setattr(security_api.security, "email_code_matches", lambda *_args: True)
    monkeypatch.setattr(security_api.store, "auth_user_id_for_legacy", lambda _id: "auth_pending")
    consumed = []
    monkeypatch.setattr(security_api.security, "consume_email_code", lambda *_args: consumed.append(True))

    async def unavailable(*_args, **_kwargs):
        raise security_api.SupabaseAuthError("unavailable", status_code=503)

    monkeypatch.setattr(security_api, "supabase_admin_update_user", unavailable)
    with pytest.raises(HTTPException) as exc:
        await security_api.confirm_verification_code(_Request({"code": "123456"}))
    assert exc.value.status_code == 503
    assert consumed == []


@pytest.mark.asyncio
async def test_password_recovery_uses_transactional_mail_for_linked_identity(monkeypatch) -> None:
    user = {"id": "usr_linked", "email": "linked@example.test"}
    monkeypatch.setattr(security_hardening.store, "get_user_by_email", lambda _email: user)
    monkeypatch.setattr(security_hardening.security, "email_send_allowed", lambda *_args, **_kw: True)
    monkeypatch.setattr(security_hardening.store, "create_password_reset", lambda *_args: None)
    sent = []

    async def deliver(**kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr(security_hardening, "_deliver", deliver)
    result = await security_hardening.password_reset_request_limited(
        _Request({"email": user["email"]})
    )
    assert result["ok"] is True
    assert len(sent) == 1
    assert sent[0]["event_type"] == "password_reset"
    assert "/reset-password?token=ih_reset_" in sent[0]["text"]


@pytest.mark.asyncio
async def test_failed_second_factor_counts_against_challenge(monkeypatch) -> None:
    challenge = {"id": "lch_1", "user_id": "usr_1"}
    monkeypatch.setattr(security_api.security, "login_challenge", lambda _hash: challenge)
    monkeypatch.setattr(security_api, "_verify_second_factor", lambda *_args: False)
    failed = []
    monkeypatch.setattr(security_api.security, "fail_login_challenge", failed.append)
    with pytest.raises(HTTPException) as exc:
        await security_api.complete_2fa_login(
            _Request({"code": "000000"}, cookies={security_api.TWO_FACTOR_COOKIE: "challenge"})
        )
    assert exc.value.status_code == 401
    assert failed == ["lch_1"]


@pytest.mark.asyncio
async def test_verification_setup_failure_does_not_strand_signup_response(monkeypatch) -> None:
    def fail_verification(**_kwargs):
        raise RuntimeError("verification storage unavailable")

    monkeypatch.setattr(
        security_api.security, "create_email_verification", fail_verification
    )
    monkeypatch.setattr(security_api.security, "email_send_allowed", lambda *_args, **_kwargs: True)

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
    current = {
        "id": "usr_pending",
        "email": "pending@example.test",
        "display_name": "Pending",
        "email_verified": False,
        "created_at": datetime(2026, 9, 14, tzinfo=UTC),
    }

    async def sign_in(**_kwargs):
        raise security_api.SupabaseAuthError(
            "Email not confirmed",
            status_code=400,
            code="email_not_confirmed",
        )

    async def resend(*_args):
        return True

    monkeypatch.setattr(security_api.store, "get_user_by_email", lambda _email: current)
    monkeypatch.setattr(
        security_api.store,
        "auth_user_id_for_legacy",
        lambda _user_id: "auth_pending",
    )
    monkeypatch.setattr(security_api.store, "create_session", lambda **_kwargs: None)
    monkeypatch.setattr(security_api, "supabase_sign_in", sign_in)
    monkeypatch.setattr(security_api, "_send_verification", resend)

    response = await security_api.login_secure(
        _Request(
            {
                "email": current["email"],
                "password": "long-enough-password",
            }
        )
    )
    payload = json.loads(response.body)

    assert payload["verification_required"] is True
    assert payload["verification_sent"] is True
    assert payload["verification_mode"] == "link_or_code"
    assert payload["verification_context"] == "signin"
    assert payload["next"] == "/verify-email"


@pytest.mark.asyncio
async def test_unverified_password_login_reports_delivery_failure(monkeypatch) -> None:
    current = {
        "id": "usr_pending",
        "email": "pending@example.test",
        "display_name": "Pending",
        "email_verified": False,
    }

    async def sign_in(**_kwargs):
        raise security_api.SupabaseAuthError(
            "Email not confirmed",
            status_code=400,
            code="email_not_confirmed",
        )

    async def fail_resend(*_args):
        return False

    monkeypatch.setattr(security_api.store, "get_user_by_email", lambda _email: current)
    monkeypatch.setattr(
        security_api.store,
        "auth_user_id_for_legacy",
        lambda _user_id: "auth_pending",
    )
    monkeypatch.setattr(security_api.store, "create_session", lambda **_kwargs: None)
    monkeypatch.setattr(security_api, "supabase_sign_in", sign_in)
    monkeypatch.setattr(security_api, "_send_verification", fail_resend)

    response = await security_api.login_secure(
        _Request(
            {
                "email": current["email"],
                "password": "long-enough-password",
            }
        )
    )
    payload = json.loads(response.body)

    assert payload["verification_required"] is True
    assert payload["verification_sent"] is False
    assert payload["verification_mode"] == "link_or_code"
    assert payload["verification_context"] == "signin"


def test_auth_me_returns_pending_identity_without_account_snapshot(monkeypatch) -> None:
    pending = {
        "id": "usr_pending",
        "email": "pending@example.test",
        "email_verified": False,
    }
    monkeypatch.setattr(control_api, "_require_user", lambda _request: pending)

    def unexpected_snapshot(_user_id):
        raise AssertionError("pending users must not require provisioned account resources")

    monkeypatch.setattr(control_api.store, "account_snapshot", unexpected_snapshot)
    payload = control_api.auth_me(object())

    assert payload["user"] == pending
    assert payload["account"] is None
    assert payload["verification_required"] is True


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
async def test_oauth_approval_rejects_unverified_signed_in_user(monkeypatch) -> None:
    monkeypatch.setattr(control_api, "_parse_form", lambda _raw: {
        "client_id": "client",
        "redirect_uri": "https://client.example/callback",
        "response_type": "code",
        "code_challenge": "challenge",
        "code_challenge_method": "S256",
        "scope": "mcp:read mcp:execute",
        "action": "approve",
    })
    monkeypatch.setattr(
        control_api,
        "_session_user",
        lambda _request: {"id": "usr_pending", "email": "pending@example.test", "email_verified": False},
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


def test_oauth_return_path_only_accepts_local_authorize_route() -> None:
    from internet_hands.security_api import _safe_oauth_return_path

    assert (
        _safe_oauth_return_path("/oauth/authorize?client_id=x&state=y")
        == "/oauth/authorize?client_id=x&state=y"
    )
    assert _safe_oauth_return_path("https://evil.example/oauth/authorize") == ""
    assert _safe_oauth_return_path("//evil.example/oauth/authorize") == ""
    assert _safe_oauth_return_path("/dashboard") == ""
    assert _safe_oauth_return_path("/oauth/authorize#fragment") == ""
