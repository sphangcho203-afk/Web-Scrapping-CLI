from __future__ import annotations

import pytest
from fastapi import HTTPException

from internet_hands import mailer, security_hardening
from internet_hands.mailer import MailError, MailResult, mail_provider, smtp_configured
from internet_hands.saas_app import app


def _iter_routes(routes, prefix: str = ""):
    for route in routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            include_context = getattr(route, "include_context", None)
            nested_prefix = f"{prefix}{getattr(include_context, 'prefix', '')}"
            yield from _iter_routes(original_router.routes, nested_prefix)
            continue
        yield route, f"{prefix}{getattr(route, 'path', '')}"


def _first_endpoint_module(path: str, method: str) -> str:
    for route, effective_path in _iter_routes(app.routes):
        methods = getattr(route, "methods", set()) or set()
        if effective_path == path and method in methods:
            return route.endpoint.__module__
    raise AssertionError(f"route {method} {path} not found")


def test_security_auth_routes_override_legacy_handlers() -> None:
    assert _first_endpoint_module("/api/auth/signup", "POST").endswith("security_api")
    assert _first_endpoint_module("/api/auth/login", "POST").endswith("security_api")
    assert _first_endpoint_module("/api/auth/github/callback", "GET").endswith("security_api")
    assert _first_endpoint_module("/api/auth/2fa/setup", "POST").endswith("security_hardening")
    assert _first_endpoint_module("/api/auth/2fa/confirm", "POST").endswith("security_hardening")
    assert _first_endpoint_module("/api/auth/password-reset/request", "POST").endswith(
        "security_hardening"
    )
    assert _first_endpoint_module("/api/auth/email-verification/send", "POST").endswith(
        "security_hardening"
    )


def test_two_factor_and_verification_routes_exist() -> None:
    expected = {
        ("/api/auth/2fa/status", "GET"),
        ("/api/auth/2fa/setup", "POST"),
        ("/api/auth/2fa/confirm", "POST"),
        ("/api/auth/2fa/challenge", "POST"),
        ("/api/auth/2fa/disable", "POST"),
        ("/api/auth/email-verification/send", "POST"),
        ("/api/auth/email-verification/confirm", "POST"),
        ("/api/auth/verify-email", "GET"),
        ("/api/security/status", "GET"),
    }
    actual = {
        (effective_path, method)
        for route, effective_path in _iter_routes(app.routes)
        for method in (getattr(route, "methods", set()) or set())
    }
    assert expected <= actual


def test_enabled_two_factor_cannot_be_replaced_by_setup(monkeypatch) -> None:
    monkeypatch.setattr(security_hardening, "_require_user", lambda _request: {"id": "usr_test"})
    monkeypatch.setattr(
        security_hardening.security,
        "account_security",
        lambda _user_id: {"totp_enabled": True},
    )
    with pytest.raises(HTTPException) as exc:
        security_hardening.two_factor_setup_protected(object())
    assert exc.value.status_code == 409


def test_smtp_provider_is_preferred(monkeypatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("RESEND_API_KEY", "resend-test")
    assert smtp_configured() is True
    assert mail_provider() == "smtp"


@pytest.mark.asyncio
async def test_smtp_failure_falls_back_to_resend(monkeypatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("RESEND_API_KEY", "resend-test")

    def fail_smtp(**_kwargs):
        raise MailError("smtp unavailable")

    async def fake_resend(**_kwargs):
        return MailResult(provider="resend", message_id="email_test")

    monkeypatch.setattr(mailer, "_send_smtp_sync", fail_smtp)
    monkeypatch.setattr(mailer, "_send_resend", fake_resend)

    result = await mailer.send_mail(
        to="user@example.com",
        subject="test",
        text="test",
        html="<p>test</p>",
    )
    assert result.provider == "resend"
    assert result.message_id == "email_test"


def test_mail_provider_none_without_credentials(monkeypatch) -> None:
    for name in (
        "SMTP_HOST",
        "SMTP_FROM_EMAIL",
        "INTERNET_HANDS_FROM_EMAIL",
        "RESEND_FROM_EMAIL",
        "RESEND_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    assert mail_provider() is None
