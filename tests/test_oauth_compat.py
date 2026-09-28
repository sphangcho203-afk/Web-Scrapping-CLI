from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from internet_hands import control_api, oauth_compat
from internet_hands.control_api import _mcp_resource
from internet_hands.oauth_compat import (
    SCOPES,
    _client_id,
    _client_payload,
    _validate_registered_client,
)


def test_oauth_metadata_advertises_offline_access() -> None:
    assert "offline_access" in SCOPES


def test_oauth_resource_is_bound_to_the_mcp_origin() -> None:
    request = Request({
        "type": "http", "scheme": "https", "server": ("preview.example", 443),
        "path": "/oauth/authorize", "headers": [(b"host", b"preview.example")],
    })
    assert _mcp_resource(request, "https://preview.example/mcp/") == "https://preview.example/mcp"
    with pytest.raises(HTTPException):
        _mcp_resource(request, "https://another.example/mcp")


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


def _oauth_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(oauth_compat.router)
    return app


def _registered_client(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("INTERNET_HANDS_OAUTH_SIGNING_SECRET", "unit-test-oauth-secret")
    return _client_id(
        {
            "redirect_uris": ["https://backend.composio.dev/api/v1/oauth/apps/add"],
            "client_name": "Composio",
            "application_type": "web",
            "iat": 1,
        }
    )


def _authorize_params(client_id: str) -> dict[str, str]:
    return {
        "client_id": client_id,
        "redirect_uri": "https://backend.composio.dev/api/v1/oauth/apps/add",
        "response_type": "code",
        "code_challenge": "A" * 43,
        "code_challenge_method": "S256",
        "state": "state-123",
        "scope": "mcp:read mcp:execute offline_access",
        "resource": "http://testserver/mcp",
    }


def test_authorize_requires_open_crawl_login_and_preserves_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_id = _registered_client(monkeypatch)
    client = TestClient(_oauth_test_app(), follow_redirects=False)
    response = client.get("/oauth/authorize", params=_authorize_params(client_id))
    assert response.status_code == 302
    assert response.headers["location"].startswith("/login?next=")
    assert "%2Foauth%2Fauthorize" in response.headers["location"]


def test_signed_in_authorize_renders_real_html_without_api_key_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_id = _registered_client(monkeypatch)
    user = {"id": "usr_1", "email": "user@example.com", "email_verified": True}
    monkeypatch.setattr(control_api, "_session_user", lambda _request: user)
    monkeypatch.setattr(oauth_compat, "_session_user", lambda _request: user, raising=False)

    client = TestClient(_oauth_test_app(), follow_redirects=False)
    response = client.get("/oauth/authorize", params=_authorize_params(client_id))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Authorize MCP connection" in response.text
    assert "Composio" in response.text
    assert "OpenCrawl API key" not in response.text
    assert "name='action' value='approve'" in response.text


def test_session_consent_issues_authorization_code_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_id = _registered_client(monkeypatch)
    user = {"id": "usr_1", "email": "user@example.com", "email_verified": True}
    monkeypatch.setattr(control_api, "_session_user", lambda _request: user)
    monkeypatch.setattr(oauth_compat, "_session_user", lambda _request: user, raising=False)
    monkeypatch.setattr(
        control_api.store,
        "account_snapshot",
        lambda _user_id: {"plan_slug": "pro", "rpm_limit": 240, "concurrent_limit": 10},
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        control_api.store,
        "create_oauth_code",
        lambda **kwargs: captured.update(kwargs),
    )

    client = TestClient(_oauth_test_app(), follow_redirects=False)
    form = _authorize_params(client_id)
    form["action"] = "approve"
    response = client.post(
        "/oauth/authorize",
        data=form,
        headers={"origin": "http://testserver"},
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith(
        "https://backend.composio.dev/api/v1/oauth/apps/add?"
    )
    assert "code=" in response.headers["location"]
    assert "state=state-123" in response.headers["location"]
    assert "iss=http%3A%2F%2Ftestserver" in response.headers["location"]
    identity = captured["identity"]
    assert identity.user_id == "usr_1"
    assert identity.api_key_id is None
    assert set(captured["scopes"]) == {"mcp:read", "mcp:execute", "offline_access"}


def test_register_rejects_non_object_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNET_HANDS_OAUTH_SIGNING_SECRET", "unit-test-oauth-secret")
    client = TestClient(_oauth_test_app(), follow_redirects=False)
    response = client.post("/oauth/register", json=["not", "metadata"])
    assert response.status_code == 400


def test_authorize_html_sets_security_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    client_id = _registered_client(monkeypatch)
    user = {"id": "usr_1", "email": "user@example.com", "email_verified": True}
    monkeypatch.setattr(control_api, "_session_user", lambda _request: user)

    client = TestClient(_oauth_test_app(), follow_redirects=False)
    response = client.get("/oauth/authorize", params=_authorize_params(client_id))

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_authorize_post_requires_explicit_approval_or_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_id = _registered_client(monkeypatch)
    user = {"id": "usr_1", "email": "user@example.com", "email_verified": True}
    monkeypatch.setattr(control_api, "_session_user", lambda _request: user)

    client = TestClient(_oauth_test_app(), follow_redirects=False)
    response = client.post(
        "/oauth/authorize",
        data=_authorize_params(client_id),
        headers={"origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert "explicit OAuth consent action" in response.text
