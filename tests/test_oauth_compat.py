from __future__ import annotations

import pytest
from fastapi import HTTPException

from internet_hands.oauth_compat import (
    SCOPES,
    _client_id,
    _client_payload,
    _validate_registered_client,
)


def test_oauth_metadata_advertises_offline_access() -> None:
    assert "offline_access" in SCOPES


def test_signed_dynamic_client_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNET_HANDS_OAUTH_SIGNING_SECRET", "unit-test-oauth-secret")
    payload = {
        "redirect_uris": ["https://chatgpt.com/oauth/callback"],
        "client_name": "ChatGPT",
        "application_type": "web",
        "iat": 1,
    }
    client_id = _client_id(payload)
    assert client_id.startswith("ih_client_")
    assert _client_payload(client_id) == payload
    _validate_registered_client(client_id, "https://chatgpt.com/oauth/callback")


def test_dynamic_client_rejects_unregistered_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNET_HANDS_OAUTH_SIGNING_SECRET", "unit-test-oauth-secret")
    client_id = _client_id(
        {
            "redirect_uris": ["https://chatgpt.com/oauth/callback"],
            "client_name": "ChatGPT",
            "application_type": "web",
            "iat": 1,
        }
    )
    with pytest.raises(HTTPException, match="redirect_uri"):
        _validate_registered_client(client_id, "https://example.com/callback")


def test_dynamic_client_rejects_tampering(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNET_HANDS_OAUTH_SIGNING_SECRET", "unit-test-oauth-secret")
    client_id = _client_id(
        {
            "redirect_uris": ["https://chatgpt.com/oauth/callback"],
            "client_name": "ChatGPT",
            "application_type": "web",
            "iat": 1,
        }
    )
    tampered = client_id[:-1] + ("A" if client_id[-1] != "A" else "B")
    assert _client_payload(tampered) is None
