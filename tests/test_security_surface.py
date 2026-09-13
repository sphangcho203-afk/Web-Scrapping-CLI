from __future__ import annotations

import pytest

from internet_hands import mailer
from internet_hands.mailer import MailError, MailResult, mail_provider, smtp_configured
from internet_hands.saas_app import app


def _first_endpoint_module(path: str, method: str) -> str:
    for route in app.routes:
        methods = getattr(route, "methods", set()) or set()
        if getattr(route, "path", None) == path and method in methods:
            return route.endpoint.__module__
    raise AssertionError(f"route {method} {path} not found")


def test_security_auth_routes_override_legacy_handlers() -> None:
    assert _first_endpoint_module("/api/auth/signup", "POST").endswith("security_api")
    assert _first_endpoint_module("/api/auth/login", "POST").endswith("security_api")
    assert _first_endpoint_module("/api/auth/github/callback", "GET").endswith("security_api")
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
        (getattr(route, "path", ""), method)
        for route in app.routes
        for method in (getattr(route, "methods", set()) or set())
    }
    assert expected <= actual


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
