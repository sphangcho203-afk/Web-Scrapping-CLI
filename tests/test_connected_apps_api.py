from __future__ import annotations

import json

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from internet_hands import connected_apps_api
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
        if request.method == "GET" and request.url.path.endswith("/connected_accounts"):
            assert request.url.params.get_list("user_ids") == ["usr_alice"]
            return httpx.Response(200, json={"items": []})
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
        if request.url.path.endswith("/connected_accounts"):
            return httpx.Response(200, json={"items": []})
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


@pytest.mark.asyncio
async def test_duplicate_active_account_requires_explicit_multi_account_opt_in() -> None:
    post_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        if request.url.path.endswith("/auth_configs"):
            return httpx.Response(200, json={"items": [_auth_config("ac_git", "github")]})
        if request.method == "GET" and request.url.path.endswith("/connected_accounts"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            **_connection("ca_existing", "github", "usr_alice"),
                            "auth_config": {"id": "ac_git", "auth_scheme": "OAUTH2"},
                        }
                    ]
                },
            )
        if request.method == "POST" and request.url.path.endswith("/connected_accounts/link"):
            post_count += 1
            return httpx.Response(
                201,
                json={
                    "redirect_url": "https://connect.composio.dev/link/new",
                    "connected_account_id": "ca_new",
                },
            )
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = ComposioConnectionService(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
        )
        with pytest.raises(HTTPException) as exc:
            await service.create_link(user_id="usr_alice", toolkit="github")
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "integration_account_exists"

        result = await service.create_link(
            user_id="usr_alice",
            toolkit="github",
            alias="second",
            allow_multiple=True,
        )

    assert post_count == 1
    assert result["connected_account_id"] == "ca_new"


@pytest.mark.asyncio
async def test_expired_account_reconnect_starts_fresh_link_without_reusing_alias() -> None:
    posted: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/connected_accounts"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            **_connection("ca_mail", "gmail", "usr_alice"),
                            "status": "EXPIRED",
                            "alias": "personal",
                            "auth_config": {"id": "ac_mail", "auth_scheme": "OAUTH2"},
                        }
                    ]
                },
            )
        if request.url.path.endswith("/auth_configs"):
            return httpx.Response(200, json={"items": [_auth_config("ac_mail", "gmail")]})
        if request.method == "POST" and request.url.path.endswith("/connected_accounts/link"):
            posted.update(json.loads(request.content))
            return httpx.Response(
                201,
                json={
                    "redirect_url": "https://connect.composio.dev/link/reconnect",
                    "connected_account_id": "ca_mail_new",
                },
            )
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = ComposioConnectionService(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
        )
        result = await service.reconnect_link(
            user_id="usr_alice",
            account_id="ca_mail",
            callback_url="https://opencrawl.example/dashboard/connections?reconnected=1",
        )

    assert posted["auth_config_id"] == "ac_mail"
    assert posted["user_id"] == "usr_alice"
    assert "alias" not in posted
    assert result["redirect_url"].endswith("/reconnect")


def test_public_connection_exposes_status_reason_but_not_secrets() -> None:
    row = _connection("ca_alice", "github", "usr_alice")
    row["status"] = "EXPIRED"
    row["status_reason"] = "refresh token revoked"

    public = _public_connection(row)

    assert public["status"] == "EXPIRED"
    assert public["status_reason"] == "refresh token revoked"
    assert "credentials" not in public


@pytest.mark.asyncio
async def test_toolkit_catalog_returns_safe_connectable_metadata() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/toolkits")
        assert request.url.params.get("search") == "mail"
        assert request.url.params.get("sort_by") == "usage"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "slug": "gmail",
                        "name": "Gmail",
                        "description": "Email tools",
                        "logo": "https://cdn.example/gmail.svg",
                        "auth_schemes": ["oauth2"],
                        "type": "native",
                        "internal_secret": "never-public",
                    }
                ],
                "next_cursor": "cursor-2",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = ComposioConnectionService(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
        )
        result = await service.toolkits(search="mail", limit=25)

    assert result == {
        "apps": [
            {
                "toolkit": "gmail",
                "name": "Gmail",
                "description": "Email tools",
                "logo": "https://cdn.example/gmail.svg",
                "auth_schemes": ["OAUTH2"],
                "type": "native",
            }
        ],
        "next_cursor": "cursor-2",
    }
    assert "never-public" not in json.dumps(result)


@pytest.mark.asyncio
async def test_toolkit_catalog_preserves_nested_metadata_for_pages_and_search() -> None:
    # Composio v3.1 GET /toolkits returns logo/description inside each item's meta.
    providers = {
        "google_maps": ("Google Maps", "Maps and place tools"),
        "docusign": ("DocuSign", "Electronic signature tools"),
        "custom_crm": ("Custom CRM", "Tools outside the bundled brand registry"),
    }
    calls: list[tuple[str | None, str | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3.1/toolkits"
        assert request.url.params.get("limit") == "25"
        search, cursor = request.url.params.get("search"), request.url.params.get("cursor")
        calls.append((search, cursor))
        if search:
            assert search == "DocuSign"
            slug, next_cursor = "docusign", None
        elif cursor:
            assert cursor == "catalog-page-2"
            slug, next_cursor = "custom_crm", None
        else:
            slug, next_cursor = "google_maps", "catalog-page-2"
        name, description = providers[slug]
        return httpx.Response(
            200,
            json={
                "items": [{
                    "slug": slug,
                    "name": name,
                    "auth_schemes": ["oauth2", "api_key"],
                    "type": "custom" if slug == "custom_crm" else "native",
                    "meta": {
                        "logo": f"https://assets.composio.dev/logos/{slug}.png",
                        "description": description,
                        "categories": [{"id": "productivity", "name": "Productivity"}],
                        "internal_secret": "never-public",
                    },
                    "credentials": {"access_token": "never-public"},
                }],
                "next_cursor": next_cursor,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = ComposioConnectionService(
            api_key="key", base_url="https://composio.test/api/v3.1", client=client,
        )
        first = await service.toolkits(limit=25)
        second = await service.toolkits(limit=25, cursor=first["next_cursor"])
        searched = await service.toolkits(search="DocuSign", limit=25, cursor="search-page-2")

    assert calls == [(None, None), (None, "catalog-page-2"), ("DocuSign", "search-page-2")]
    for result, slug in [(first, "google_maps"), (second, "custom_crm"), (searched, "docusign")]:
        row = result["apps"][0]
        assert row["toolkit"] == slug
        assert row["name"] == providers[slug][0]
        assert row["description"] == providers[slug][1]
        assert row["logo"] == f"https://assets.composio.dev/logos/{slug}.png"
        assert row["auth_schemes"] == ["OAUTH2", "API_KEY"]
        assert "never-public" not in json.dumps(result)
    assert second["next_cursor"] is None
    assert searched["next_cursor"] is None


@pytest.mark.asyncio
async def test_catalog_metadata_keeps_flattened_compatibility_and_ignores_invalid_meta() -> None:
    malformed_meta = [None, [], "not an object", 1, True]
    rows = [
        {
            "slug": f"legacy_{index}",
            "meta": meta,
            "logo": "https://cdn.example/legacy.svg",
            "description": "Legacy description",
        }
        for index, meta in enumerate(malformed_meta)
    ]
    rows.extend([
        {
            "slug": "nested_wins",
            "logo": "https://cdn.example/old.svg",
            "description": "Old description",
            "meta": {
                "logo": "https://cdn.example/current.svg",
                "description": "Current description" + "x" * 400,
            },
        },
        {
            "slug": "invalid_fields",
            "logo": "https://cdn.example/fallback.svg",
            "description": "Fallback description",
            "meta": {"logo": {"url": "https://cdn.example/invalid.svg"}, "description": []},
        },
        {"slug": "missing", "meta": {"logo": None, "description": None}},
    ])

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": rows})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ComposioConnectionService(api_key="key", client=client).toolkits()

    apps = {row["toolkit"]: row for row in result["apps"]}
    for index in range(len(malformed_meta)):
        assert apps[f"legacy_{index}"]["logo"] == "https://cdn.example/legacy.svg"
        assert apps[f"legacy_{index}"]["description"] == "Legacy description"
    assert apps["nested_wins"]["logo"] == "https://cdn.example/current.svg"
    assert apps["nested_wins"]["description"].startswith("Current description")
    assert len(apps["nested_wins"]["description"]) == 320
    assert apps["invalid_fields"]["logo"] == "https://cdn.example/fallback.svg"
    assert apps["invalid_fields"]["description"] == "Fallback description"
    assert apps["missing"]["logo"] is None
    assert apps["missing"]["description"] is None


@pytest.mark.asyncio
async def test_catalog_logos_are_https_strings_without_embedded_credentials() -> None:
    invalid_logos = [
        None, False, 123, {"url": "https://cdn.example/logo.svg"}, ["https://cdn.example/logo.svg"],
        "", "not a URL", "/logo.svg", "//cdn.example/logo.svg", "http://cdn.example/logo.svg",
        "javascript:alert(1)", "data:image/svg+xml,<svg></svg>",
        "https://user:password@cdn.example/logo.svg", "https://user@cdn.example/logo.svg",
        "https://:password@cdn.example/logo.svg", "https:///logo.svg",
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"items": [
                {"slug": f"unsafe_{index}", "meta": {"logo": value}}
                for index, value in enumerate(invalid_logos)
            ] + [
                {"slug": "safe", "meta": {"logo": " https://cdn.example/logo.svg "}},
                {"slug": "safe_fallback", "meta": {"logo": "javascript:alert(1)"},
                 "logo": "https://cdn.example/fallback.svg"},
            ]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ComposioConnectionService(api_key="key", client=client).toolkits()

    apps = {row["toolkit"]: row for row in result["apps"]}
    assert all(apps[f"unsafe_{index}"]["logo"] is None for index in range(len(invalid_logos)))
    assert apps["safe"]["logo"] == "https://cdn.example/logo.svg"
    assert apps["safe_fallback"]["logo"] == "https://cdn.example/fallback.svg"


@pytest.mark.asyncio
async def test_saved_apps_normalize_flat_and_nested_toolkit_logos_without_leaking_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configs = [_auth_config("ac_maps", "google_maps"), _auth_config("ac_docu", "docusign")]
    configs[0]["toolkit"]["name"] = "Google Maps"
    configs[1]["toolkit"] = {
        "slug": "docusign",
        "name": "DocuSign",
        "meta": {"logo": "https://cdn.example/docusign.svg", "description": "Sign documents"},
    }
    missing = _auth_config("ac_custom_first", "custom_crm")
    missing["toolkit"]["logo"] = None
    later = _auth_config("ac_custom_second", "custom_crm")
    later["toolkit"]["logo"] = {"url": "https://cdn.example/invalid.svg"}
    later["toolkit"]["meta"] = {"logo": "https://cdn.example/custom-crm.svg"}
    unsafe = _auth_config("ac_unsafe", "unsafe_app")
    unsafe["toolkit"]["logo"] = "http://cdn.example/insecure.svg"
    configs.extend([missing, later, unsafe])
    for config in configs:
        config["credentials"] = {"access_token": "must-never-leak"}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth_configs"):
            return httpx.Response(200, json={"items": configs})
        if request.url.path.endswith("/connected_accounts"):
            return httpx.Response(200, json={"items": [_connection("ca_maps", "google_maps", "u1")]})
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = ComposioConnectionService(api_key="key", client=client)
        monkeypatch.setattr(connected_apps_api, "ComposioConnectionService", lambda: service)
        monkeypatch.setattr(connected_apps_api, "_require_user", lambda request: {"id": "u1"})
        result = await connected_apps_api.integration_apps(Request({"type": "http"}))

    apps = {row["toolkit"]: row for row in result["apps"]}
    assert apps["google_maps"]["logo"] == "https://cdn.example/google_maps.svg"
    assert apps["google_maps"]["active_accounts"] == 1
    assert apps["docusign"]["logo"] == "https://cdn.example/docusign.svg"
    assert apps["docusign"]["description"] == "Sign documents"
    assert apps["custom_crm"]["logo"] == "https://cdn.example/custom-crm.svg"
    assert apps["custom_crm"]["auth_config_count"] == 2
    assert apps["unsafe_app"]["logo"] is None
    assert "must-never-leak" not in json.dumps(result)


@pytest.mark.asyncio
async def test_connect_auto_creates_composio_managed_auth_when_missing() -> None:
    posted_auth: dict[str, object] = {}
    posted_link: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/connected_accounts"):
            return httpx.Response(200, json={"items": []})
        if request.method == "GET" and request.url.path.endswith("/auth_configs"):
            return httpx.Response(200, json={"items": []})
        if request.method == "POST" and request.url.path.endswith("/auth_configs"):
            posted_auth.update(json.loads(request.content))
            return httpx.Response(
                201,
                json={
                    "toolkit": {"slug": "gmail"},
                    "auth_config": {
                        "id": "ac_gmail_managed",
                        "auth_scheme": "OAUTH2",
                        "is_composio_managed": True,
                    },
                },
            )
        if request.method == "POST" and request.url.path.endswith("/connected_accounts/link"):
            posted_link.update(json.loads(request.content))
            return httpx.Response(
                201,
                json={
                    "redirect_url": "https://connect.composio.dev/link/gmail",
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
            toolkit="gmail",
            callback_url="https://opencrawl.example/dashboard/connections?connected=gmail",
        )

    assert posted_auth == {
        "toolkit": {"slug": "gmail"},
        "auth_config": {
            "type": "use_composio_managed_auth",
            "credentials": {},
            "restrict_to_following_tools": [],
        },
    }
    assert posted_link["auth_config_id"] == "ac_gmail_managed"
    assert posted_link["user_id"] == "usr_alice"
    assert result["auth_config_id"] == "ac_gmail_managed"


@pytest.mark.asyncio
async def test_connect_reports_setup_required_when_managed_auth_is_not_supported() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/connected_accounts"):
            return httpx.Response(200, json={"items": []})
        if request.method == "GET" and request.url.path.endswith("/auth_configs"):
            return httpx.Response(200, json={"items": []})
        if request.method == "POST" and request.url.path.endswith("/auth_configs"):
            return httpx.Response(
                422,
                json={"message": "toolkit requires custom credentials"},
            )
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = ComposioConnectionService(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
        )
        with pytest.raises(HTTPException) as exc:
            await service.create_link(user_id="usr_alice", toolkit="custom_toolkit")

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "integration_auth_setup_required"


@pytest.mark.asyncio
async def test_owned_connected_account_can_be_renamed_and_paused() -> None:
    patches: list[tuple[str, dict[str, object]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/connected_accounts"):
            return httpx.Response(
                200,
                json={"items": [_connection("ca_work", "github", "usr_alice")]},
            )
        if request.method == "PATCH" and request.url.path.endswith("/connected_accounts/ca_work"):
            patches.append((request.url.path, json.loads(request.content)))
            return httpx.Response(200, json={"success": True, "id": "ca_work", "status": "ACTIVE"})
        if request.method == "PATCH" and request.url.path.endswith("/connected_accounts/ca_work/status"):
            patches.append((request.url.path, json.loads(request.content)))
            return httpx.Response(200, json={"success": True})
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = ComposioConnectionService(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
        )
        await service.update_alias(
            user_id="usr_alice",
            account_id="ca_work",
            alias="work-github",
        )
        await service.set_enabled(
            user_id="usr_alice",
            account_id="ca_work",
            enabled=False,
        )

    assert patches == [
        ("/api/v3.1/connected_accounts/ca_work", {"alias": "work-github"}),
        ("/api/v3.1/connected_accounts/ca_work/status", {"enabled": False}),
    ]


@pytest.mark.asyncio
async def test_cross_tenant_connected_account_cannot_be_renamed_or_paused() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/connected_accounts"):
            return httpx.Response(
                200,
                json={"items": [_connection("ca_bob", "github", "usr_bob")]},
            )
        raise AssertionError("mutation should never be sent for another tenant")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = ComposioConnectionService(
            api_key="key",
            base_url="https://composio.test/api/v3.1",
            client=client,
        )
        with pytest.raises(HTTPException) as rename_exc:
            await service.update_alias(
                user_id="usr_alice",
                account_id="ca_bob",
                alias="not-mine",
            )
        with pytest.raises(HTTPException) as pause_exc:
            await service.set_enabled(
                user_id="usr_alice",
                account_id="ca_bob",
                enabled=False,
            )

    assert rename_exc.value.status_code == 404
    assert pause_exc.value.status_code == 404
