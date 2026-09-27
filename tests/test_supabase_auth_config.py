from __future__ import annotations

import pytest
from starlette.requests import Request

from internet_hands.security_api import _mail_origin
from internet_hands.supabase_auth import (
    SupabaseAuthError,
    _headers,
    configuration_status,
)


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

    assert configuration_status() == {
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

    assert configuration_status()["secret_key"] is False
    with pytest.raises(SupabaseAuthError) as exc:
        _headers(secret=True)

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

    headers = _headers(secret=True)
    assert headers["apikey"] == "legacy-service-role-fixture"
    assert headers["Authorization"] == "Bearer legacy-service-role-fixture"
    assert configuration_status()["configured"] is True


def test_newlines_in_auth_keys_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "publishable\nfixture")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_fixture")

    assert configuration_status()["publishable_key"] is False
    with pytest.raises(SupabaseAuthError) as exc:
        _headers(secret=False)

    assert exc.value.code == "auth_configuration_invalid"


def _request(host: str = "preview.example.test") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/signup",
            "raw_path": b"/signup",
            "query_string": b"",
            "headers": [
                (b"host", host.encode("ascii")),
                (b"x-forwarded-proto", b"https"),
            ],
            "client": ("127.0.0.1", 12345),
            "server": (host, 443),
        }
    )


def test_mail_origin_stays_on_preview_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERNET_HANDS_PUBLIC_ORIGIN", raising=False)
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "old-production.example.test")

    assert _mail_origin(_request()) == "https://preview.example.test"


def test_mail_origin_can_be_explicitly_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNET_HANDS_PUBLIC_ORIGIN", "https://opencrawl.example.test")

    assert _mail_origin(_request()) == "https://opencrawl.example.test"
