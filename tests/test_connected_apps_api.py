from __future__ import annotations

import json

import httpx
import pytest
from fastapi import HTTPException

from internet_hands.connected_apps_api import (
    ComposioConnectionService,
    _public_connection,
)


def _auth_config(config_id: str, toolkit: str, *, status: str = "ENABLED") -> dict:
    return {
        "id": config_id,
        "name": f"{toolkit} auth",
        "status": status,
        "auth_scheme": "OAUTH2",
        "is_composio_managed": True,
        "toolkit": {"slug": toolkit, "logo": f"https://cdn.example/{toolkit}.svg"},
    }


def _connection(account_id: str, toolkit: str, user_id: str) -> dict:
    return {
        "id": account_id,
        "user_id": user_id,
        "status": "ACTIVE",
        "alias": "primary",
        "toolkit": {"slug": toolkit},
        "auth_config": {"id": "ac_1", "auth_scheme": "OAUTH2", "is_composio_managed": True},
        "credentials": {"access_token": "must-never-leak"},
    }


@pytest.mark.asyncio
async def test_user_connections_are_filtered_again_after_provider_response() -> None:
    seen_user_ids: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/connected_accounts")
        seen_user_ids.extend(request.url.params.get_list("user_ids"))
        return httpx.Response(
            200,
            json={
                "items": [
                    _connection("ca_alice", "github", "usr_alice"),
                    _connection("ca_bob", "github", "usr_bob"),
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = ComposioConnectionService(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
        )
        rows = await service.user_connections("usr_alice")

    assert seen_user_ids == ["usr_alice"]
    assert [row["id"] for row in rows] == ["ca_alice"]


@pytest.mark.asyncio
async def test_create_link_resolves_enabled_config_and_binds_user() -> None:
    posted: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/auth_configs"):
            assert request.url.params.get("toolkit_slug") == "github"
            return httpx.Response(200, json={"items": [_auth_config("ac_git", "github")]})
        if request.method == "POST" and request.url.path.endswith("/connected_accounts/link"):
            posted.update(json.loads(request.content))
            return httpx.Response(
                201,
                json={
                    "redirect_url": "https://connect.composio.dev/link/abc",
                    "expires_at": "2026-09-27T18:00:00Z",
                    "connected_account_id": "ca_pending",
                },
            )
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = ComposioConnectionService(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
        )
        result = await service.create_link(
            user_id="usr_alice",
            toolkit="github",
            alias="work",
            callback_url="https://opencrawl.example/dashboard#integrations",
        )

    assert posted == {
        "auth_config_id": "ac_git",
        "user_id": "usr_alice",
        "alias": "work",
        "callback_url": "https://opencrawl.example/dashboard#integrations",
    }
    assert result["redirect_url"] == "https://connect.composio.dev/link/abc"


@pytest.mark.asyncio
async def test_create_link_rejects_non_https_provider_redirect() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth_configs"):
            return httpx.Response(200, json={"items": [_auth_config("ac_git", "github")]})
        if request.url.path.endswith("/connected_accounts/link"):
            return httpx.Response(201, json={"redirect_url": "javascript:alert(1)"})
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = ComposioConnectionService(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
        )
        with pytest.raises(HTTPException) as exc:
            await service.create_link(user_id="usr_alice", toolkit="github")

    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_multiple_auth_configs_fail_closed_without_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCRAWL_COMPOSIO_AUTH_CONFIGS", raising=False)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/auth_configs")
        return httpx.Response(
            200,
            json={"items": [_auth_config("ac_one", "github"), _auth_config("ac_two", "github")]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = ComposioConnectionService(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
        )
        with pytest.raises(HTTPException) as exc:
            await service.resolve_auth_config("github")

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "integration_auth_config_ambiguous"


@pytest.mark.asyncio
async def test_env_auth_config_default_is_validated_against_toolkit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAWL_COMPOSIO_AUTH_CONFIGS", '{"github":"ac_git"}')

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"items": [_auth_config("ac_git", "github"), _auth_config("ac_other", "github")]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = ComposioConnectionService(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
        )
        selected = await service.resolve_auth_config("github")

    assert selected["id"] == "ac_git"


@pytest.mark.asyncio
async def test_disconnect_requires_owned_account_before_delete() -> None:
    methods: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"items": [_connection("ca_alice", "github", "usr_alice")]})
        if request.method == "DELETE":
            assert request.url.path.endswith("/connected_accounts/ca_alice")
            return httpx.Response(204)
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = ComposioConnectionService(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
        )
        await service.disconnect(user_id="usr_alice", account_id="ca_alice")

    assert methods == ["GET", "DELETE"]


def test_public_connection_never_exposes_credentials() -> None:
    public = _public_connection(_connection("ca_alice", "github", "usr_alice"))
    encoded = json.dumps(public)
    assert "must-never-leak" not in encoded
    assert "credentials" not in public
    assert public["id"] == "ca_alice"
    assert public["toolkit"] == "github"
