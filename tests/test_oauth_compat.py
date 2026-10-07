from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from internet_hands import control_api, oauth_compat, saas_app
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


class _ConsentForm(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.method = ""
        self.fields: dict[str, str] = {}
        self.password_field = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form":
            self.method = attributes.get("method") or ""
        if tag == "input" and attributes.get("name"):
            self.fields[str(attributes["name"])] = attributes.get("value") or ""
            if attributes["name"] == "api_key":
                self.password_field = attributes.get("type") == "password"


@pytest.mark.asyncio
@pytest.mark.parametrize("client_name, redirect", [
    ("ChatGPT", "https://chatgpt.com/connector_platform_oauth_redirect"),
    ("Grok", "https://grok.com/connectors-oauth-exchange-code/"),
])
@pytest.mark.parametrize("scope, expected", [
    ("mcp:read mcp:execute offline_access", 302),
    ("mcp:read account:read offline_access", 403),
])
async def test_mcp_oauth_consent_with_scoped_key_and_refresh(
    monkeypatch: pytest.MonkeyPatch, client_name: str, redirect: str, scope: str, expected: int,
) -> None:
    monkeypatch.setenv("INTERNET_HANDS_OAUTH_SIGNING_SECRET", "unit-test-oauth-secret")
    store = _OAuthStore()
    monkeypatch.setattr(control_api, "store", store)
    identity = AuthIdentity("usr_test", "key_test", ["mcp:read", "mcp:execute"], "free", 10, "api_key")
    monkeypatch.setattr(control_api, "authenticate_secret", lambda *_: identity)
    monkeypatch.setattr(control_api, "_session_user", lambda _: None)
    verifier = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=saas_app.app),
        base_url="https://opencrawl.top", trust_env=False,
    ) as client:
        registered = await client.post("/oauth/register", json={
            "client_name": client_name, "redirect_uris": [redirect],
            "token_endpoint_auth_method": "none",
        })
        assert registered.status_code == 200
        client_id = registered.json()["client_id"]
        parameters = {
            "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
            "code_challenge": pkce_s256(verifier), "code_challenge_method": "S256",
            "state": "state-test & <script>", "scope": scope,
        }
        consent = await client.get("/oauth/authorize", params=parameters)
        assert consent.status_code == 200
        assert consent.headers["content-type"] == "text/html; charset=utf-8"
        assert consent.headers["cache-control"] == "no-store"
        assert consent.text.startswith("<!doctype html>")
        assert "<title>Authorize OpenCrawl</title>" in consent.text
        assert "<script>" not in consent.text
        form = _ConsentForm()
        form.feed(consent.text)
        assert form.method == "post" and form.password_field
        assert form.fields == {**parameters, "api_key": ""}
        assert not store.codes and not store.tokens
        response = await client.post("/oauth/authorize", data={
            **form.fields, "api_key": "local-test-only",
        })
        assert response.status_code == expected
        if expected == 403:
            assert not store.codes and not store.tokens
            return
        query = parse_qs(urlparse(response.headers["location"]).query)
        assert query["state"] == [parameters["state"]]
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
@pytest.mark.parametrize("signed_in", [False, True])
async def test_consent_page_renders_account_hint_safely(
    monkeypatch: pytest.MonkeyPatch, signed_in: bool,
) -> None:
    monkeypatch.setenv("INTERNET_HANDS_OAUTH_SIGNING_SECRET", "unit-test-oauth-secret")
    user = {"email": "owner+<script>@example.com"} if signed_in else None
    monkeypatch.setattr(control_api, "_session_user", lambda _: user)
    redirect = "https://grok.com/connectors-oauth-exchange-code/"
    client_id = _client_id({"redirect_uris": [redirect]})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=saas_app.app),
        base_url="https://opencrawl.top", trust_env=False,
    ) as client:
        response = await client.get("/oauth/authorize", params={
            "client_id": client_id, "redirect_uri": redirect,
            "code_challenge": pkce_s256("local-test-verifier"),
        })
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert ("Signed in as" in response.text) is signed_in
    assert "<script>" not in response.text
    if signed_in:
        assert "owner+&lt;script&gt;@example.com" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["client_id", "redirect_uri", "response_type", "code_challenge"])
async def test_invalid_authorization_request_never_renders_consent(
    monkeypatch: pytest.MonkeyPatch, invalid: str,
) -> None:
    monkeypatch.setenv("INTERNET_HANDS_OAUTH_SIGNING_SECRET", "unit-test-oauth-secret")
    redirect = "https://grok.com/connectors-oauth-exchange-code/"
    parameters = {
        "client_id": _client_id({"redirect_uris": [redirect]}), "redirect_uri": redirect,
        "response_type": "code", "code_challenge": pkce_s256("local-test-verifier"),
    }
    parameters[invalid] = "" if invalid == "code_challenge" else "invalid"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=saas_app.app),
        base_url="https://opencrawl.top", trust_env=False,
    ) as client:
        response = await client.get("/oauth/authorize", params=parameters)
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/json"
    assert "Allow connection" not in response.text


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
