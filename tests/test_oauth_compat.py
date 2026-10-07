from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from internet_hands import control_api, oauth_compat
from internet_hands.auth import pkce_s256, sha256_text
from internet_hands.control_store import AuthIdentity
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


class _OAuthStore:
    def __init__(self) -> None:
        self.codes: dict[str, dict[str, Any]] = {}
        self.tokens: list[dict[str, Any]] = []

    def get_user(self, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "email_verified": True}

    def create_oauth_code(self, **values: Any) -> None:
        identity = values.pop("identity")
        self.codes[values["code_hash"]] = {
            **values, "user_id": identity.user_id, "api_key_id": identity.api_key_id,
        }

    def consume_oauth_code(self, code_hash: str) -> dict[str, Any] | None:
        return self.codes.pop(code_hash, None)

    def create_oauth_token(self, **values: Any) -> None:
        self.tokens.append(values)

    def consume_refresh_token(self, refresh_hash: str, client_id: str) -> dict[str, Any] | None:
        for token in self.tokens:
            if token["refresh_hash"] == refresh_hash and token["client_id"] == client_id:
                token["refresh_hash"] = "consumed"
                return token
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("scope, expected", [
    ("mcp:read mcp:execute offline_access", 302),
    ("mcp:read account:read offline_access", 403),
])
async def test_chatgpt_oauth_with_scoped_key_and_refresh(
    monkeypatch: pytest.MonkeyPatch, scope: str, expected: int,
) -> None:
    monkeypatch.setenv("INTERNET_HANDS_OAUTH_SIGNING_SECRET", "unit-test-oauth-secret")
    store = _OAuthStore()
    monkeypatch.setattr(control_api, "store", store)
    identity = AuthIdentity("usr_test", "key_test", ["mcp:read", "mcp:execute"], "free", 10, "api_key")
    monkeypatch.setattr(control_api, "authenticate_secret", lambda *_: identity)
    app = FastAPI()
    app.include_router(oauth_compat.router)
    app.include_router(control_api.router)
    redirect = "https://chatgpt.com/connector_platform_oauth_redirect"
    verifier = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://opencrawl.top", trust_env=False,
    ) as client:
        registered = await client.post("/oauth/register", json={
            "client_name": "ChatGPT", "redirect_uris": [redirect],
            "token_endpoint_auth_method": "none",
        })
        assert registered.status_code == 200
        client_id = registered.json()["client_id"]
        response = await client.post("/oauth/authorize", data={
            "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
            "code_challenge": pkce_s256(verifier), "code_challenge_method": "S256",
            "state": "state-test", "scope": scope, "api_key": "local-test-only",
        })
        assert response.status_code == expected
        if expected == 403:
            assert not store.codes and not store.tokens
            return
        query = parse_qs(urlparse(response.headers["location"]).query)
        assert query["state"] == ["state-test"]
        assert query["iss"] == ["https://opencrawl.top"]
        exchanged = await client.post("/oauth/token", data={
            "grant_type": "authorization_code", "client_id": client_id,
            "redirect_uri": redirect, "code": query["code"][0], "code_verifier": verifier,
        })
        assert exchanged.status_code == 200
        tokens = exchanged.json()
        assert set(tokens["scope"].split()) == set(scope.split())
        assert store.tokens[0]["access_hash"] == sha256_text(tokens["access_token"])
        refreshed = await client.post("/oauth/token", data={
            "grant_type": "refresh_token", "client_id": client_id,
            "refresh_token": tokens["refresh_token"],
        })
        assert refreshed.status_code == 200
        assert refreshed.json()["access_token"] != tokens["access_token"]
        assert refreshed.json()["scope"] == tokens["scope"]


@pytest.mark.asyncio
async def test_path_specific_resource_metadata_matches_root_document() -> None:
    app = FastAPI()
    app.include_router(oauth_compat.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://opencrawl.top", trust_env=False,
    ) as client:
        root = await client.get("/.well-known/oauth-protected-resource")
        specific = await client.get("/.well-known/oauth-protected-resource/mcp")
    assert root.status_code == specific.status_code == 200
    assert root.json() == specific.json()
    assert specific.json()["resource"] == "https://opencrawl.top/mcp"
