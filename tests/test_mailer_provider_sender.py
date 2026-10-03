from __future__ import annotations

from internet_hands import mailer


def _disable_control_db(monkeypatch) -> None:
    monkeypatch.delenv("INTERNET_HANDS_CONTROL_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("INTERNET_HANDS_POSTGRES_DSN", raising=False)
    mailer._control_store.cache_clear()


def test_resend_sender_does_not_inherit_smtp_sender(monkeypatch) -> None:
    _disable_control_db(monkeypatch)
    monkeypatch.setenv("SMTP_FROM_EMAIL", "legacy-smtp@example.net")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("SMTP_FROM_NAME", "Internet Hands")

    assert mailer._from_header("resend") == "OpenCrawl <noreply@example.com>"
    assert mailer._from_header("smtp") == "OpenCrawl <legacy-smtp@example.net>"


def test_resend_configuration_uses_resend_sender(monkeypatch) -> None:
    _disable_control_db(monkeypatch)
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "legacy-smtp@example.net")

    assert mailer.resend_configured() is True


def test_database_mail_settings_prefer_vault_and_sender_profiles(monkeypatch) -> None:
    class FakeStore:
        configured = True

        def get_platform_integration(self, key: str):
            assert key == "transactional_email"
            return {
                "provider": "resend",
                "enabled": True,
                "secret_name": "opencrawl_resend_api_key",
                "config": {
                    "from_name": "OpenCrawl",
                    "default_from_email": "notifications@opencrawl.top",
                    "reply_to_email": "support@opencrawl.top",
                    "senders": {
                        "auth": "auth@opencrawl.top",
                        "billing": "billing@opencrawl.top",
                    },
                },
            }

        def get_vault_secret(self, name: str):
            assert name == "opencrawl_resend_api_key"
            return "vault-resend-key"

    monkeypatch.setenv("RESEND_API_KEY", "legacy-env-key")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "legacy@example.com")
    monkeypatch.setattr(mailer, "_control_store", lambda: FakeStore())

    settings = mailer._mail_settings()

    assert settings.source == "database"
    assert settings.provider == "resend"
    assert settings.resend_api_key == "vault-resend-key"
    assert settings.default_from_email == "notifications@opencrawl.top"
    assert settings.reply_to_email == "support@opencrawl.top"
    assert mailer._from_header("resend", settings, "auth") == (
        "OpenCrawl <auth@opencrawl.top>"
    )

    snapshot = mailer.mail_settings_snapshot()
    assert snapshot["source"] == "database"
    assert snapshot["credential_configured"] is True
    assert "resend_api_key" not in snapshot


def test_disabled_database_integration_blocks_environment_fallback(monkeypatch) -> None:
    class FakeStore:
        configured = True

        def get_platform_integration(self, key: str):
            return {
                "provider": "resend",
                "enabled": False,
                "secret_name": "opencrawl_resend_api_key",
                "config": {"default_from_email": "notifications@opencrawl.top"},
            }

        def get_vault_secret(self, name: str):
            return "vault-resend-key"

    monkeypatch.setenv("RESEND_API_KEY", "env-key")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setattr(mailer, "_control_store", lambda: FakeStore())

    settings = mailer._mail_settings()

    assert settings.source == "database"
    assert settings.enabled is False
    assert mailer.mail_provider(settings) is None
    assert mailer.resend_configured(settings) is False


def test_database_failure_uses_environment_fallback(monkeypatch) -> None:
    class FailingStore:
        configured = True

        def get_platform_integration(self, key: str):
            raise RuntimeError("database unavailable")

    monkeypatch.setenv("MAIL_PROVIDER", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "env-key")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setattr(mailer, "_control_store", lambda: FailingStore())

    settings = mailer._mail_settings()

    assert settings.source == "environment"
    assert mailer.mail_provider(settings) == "resend"


def test_supabase_vault_lookup_prefers_modern_secret_key(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class FakeResponse:
        is_success = True

        @staticmethod
        def json():
            return "vault-value"

    def fake_post(url: str, *, headers, json, timeout: float):
        captured["url"] = url
        captured["apikey"] = headers["apikey"]
        captured["authorization"] = headers["Authorization"]
        captured["secret_name"] = json["p_secret_name"]
        captured["timeout"] = str(timeout)
        return FakeResponse()

    mailer._VAULT_SECRET_CACHE.clear()
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "modern-secret")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "legacy-secret")
    monkeypatch.setattr(mailer.httpx, "post", fake_post)

    value = mailer._supabase_vault_secret("opencrawl_resend_api_key")

    assert value == "vault-value"
    assert captured["apikey"] == "modern-secret"
    assert captured["authorization"] == "Bearer modern-secret"
    assert captured["secret_name"] == "opencrawl_resend_api_key"

