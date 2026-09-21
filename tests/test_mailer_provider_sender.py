from __future__ import annotations

from internet_hands import mailer


def test_resend_sender_does_not_inherit_smtp_sender(monkeypatch) -> None:
    monkeypatch.setenv("SMTP_FROM_EMAIL", "legacy-smtp@example.net")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("SMTP_FROM_NAME", "Internet Hands")

    assert mailer._from_header("resend") == "Internet Hands <noreply@example.com>"
    assert mailer._from_header("smtp") == "Internet Hands <legacy-smtp@example.net>"


def test_resend_configuration_uses_resend_sender(monkeypatch) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "legacy-smtp@example.net")

    assert mailer.resend_configured() is True
