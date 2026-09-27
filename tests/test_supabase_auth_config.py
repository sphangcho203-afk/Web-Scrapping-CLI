from __future__ import annotations

from types import SimpleNamespace

import pytest

from internet_hands import security_api, supabase_auth


_ENV_NAMES = (
    "SUPABASE_URL",
    "SUPABASE_PUBLISHABLE_KEY",
    "SUPABASE_SECRET_KEY",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
)


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_supabase_configuration_status_is_safe_and_boolean(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_fixture")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_fixture")

    assert supabase_auth.configuration_status() == {
        "configured": True,
        "url": True,
        "publishable_key": True,
        "secret_key": True,
    }


def test_non_ascii_server_key_fails_closed_with_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_fixture")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_“copied-with-smart-quotes”")

    assert supabase_auth.configuration_status()["secret_key"] is False
    with pytest.raises(supabase_auth.SupabaseAuthError) as exc:
        supabase_auth._headers(secret=True)

    assert exc.value.status_code == 503
    assert exc.value.code == "auth_configuration_invalid"
    assert "raw ASCII value" in str(exc.value)


def test_valid_legacy_service_role_key_can_rescue_malformed_modern_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_fixture")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "broken—secret")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "legacy-service-role-fixture")

    headers = supabase_auth._headers(secret=True)
    assert headers["apikey"] == "legacy-service-role-fixture"
    assert headers["Authorization"] == "Bearer legacy-service-role-fixture"
    assert supabase_auth.configuration_status()["configured"] is True


def test_newlines_in_auth_keys_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "publishable\nfixture")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_fixture")

    assert supabase_auth.configuration_status()["publishable_key"] is False
    with pytest.raises(supabase_auth.SupabaseAuthError) as exc:
        supabase_auth._headers(secret=False)

    assert exc.value.code == "auth_configuration_invalid"


def _request(host: str = "preview.example.test"):
    return SimpleNamespace(
        headers={"host": host, "x-forwarded-proto": "https"},
        url=SimpleNamespace(scheme="https", netloc=host),
    )


def test_mail_origin_stays_on_preview_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERNET_HANDS_PUBLIC_ORIGIN", raising=False)
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "old-production.example.test")

    assert security_api._mail_origin(_request()) == "https://preview.example.test"


def test_mail_origin_can_be_explicitly_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNET_HANDS_PUBLIC_ORIGIN", "https://opencrawl.example.test")

    assert security_api._mail_origin(_request()) == "https://opencrawl.example.test"
