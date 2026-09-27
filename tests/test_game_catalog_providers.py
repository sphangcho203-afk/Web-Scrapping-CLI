from __future__ import annotations

import httpx
import pytest

from internet_hands.game_catalog_capabilities import build_game_catalog_capabilities
from internet_hands.game_catalog_providers import (
    IgdbGamingCatalogProvider,
    RawgGamingCatalogProvider,
)


@pytest.mark.asyncio
async def test_rawg_search_injects_server_key_and_bounds_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.rawg.io"
        params = request.url.params
        assert params["key"] == "rawg-secret"
        assert params["search"] == "Halo"
        assert params["page_size"] == "40"
        assert "api_key" not in params
        return httpx.Response(200, json={"count": 0, "results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RawgGamingCatalogProvider(api_key="rawg-secret", client=client)
        result = await provider.execute(
            "search-games",
            {
                "query": "Halo",
                "limit": 999,
                "api_key": "caller-secret",
            },
        )

    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_rawg_game_detail_rejects_path_injection() -> None:
    provider = RawgGamingCatalogProvider(api_key="rawg-secret")
    with pytest.raises(ValueError):
        await provider.execute(
            "game-detail",
            {"id_or_slug": "../../admin"},
        )


@pytest.mark.asyncio
async def test_igdb_uses_client_credentials_without_scope_forging() -> None:
    seen_token = False
    seen_game = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_token, seen_game
        if request.url.host == "id.twitch.tv":
            seen_token = True
            assert request.url.params["client_id"] == "igdb-client"
            assert request.url.params["client_secret"] == "igdb-secret"
            assert request.url.params["grant_type"] == "client_credentials"
            assert "scope" not in request.url.params
            return httpx.Response(
                200,
                json={
                    "access_token": "server-token",
                    "expires_in": 3600,
                    "token_type": "bearer",
                },
            )

        assert request.url == "https://api.igdb.com/v4/games"
        seen_game = True
        assert request.headers["client-id"] == "igdb-client"
        assert request.headers["authorization"] == "Bearer server-token"
        body = request.content.decode()
        assert 'search "Halo";' in body
        assert "limit 50;" in body
        assert "caller-token" not in body
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = IgdbGamingCatalogProvider(
            client_id="igdb-client",
            client_secret="igdb-secret",
            client=client,
        )
        result = await provider.execute(
            "search-games",
            {
                "query": "Halo",
                "limit": 999,
                "authorization": "caller-token",
                "scope": "user:read",
            },
        )

    assert seen_token is True
    assert seen_game is True
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_igdb_search_escapes_query_instead_of_accepting_raw_apicalypse() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "id.twitch.tv":
            return httpx.Response(
                200,
                json={"access_token": "token", "expires_in": 3600},
            )
        body = request.content.decode()
        assert body.startswith('search "Halo\\\"  fields * "; ')
        assert '; fields *;' not in body
        assert "fields id,name,slug,summary,first_release_date" in body
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = IgdbGamingCatalogProvider(
            client_id="igdb-client",
            client_secret="igdb-secret",
            client=client,
        )
        await provider.execute(
            "search-games",
            {"query": 'Halo"; fields *;'},
        )


def test_game_catalog_capabilities_use_documented_provider_fallbacks() -> None:
    capabilities = {item.id: item for item in build_game_catalog_capabilities()}
    search = capabilities["games.catalog.search"]
    assert [candidate.provider for candidate in search.candidates] == ["igdb", "rawg"]
    assert "games.platform.search" in capabilities
    assert "games.developer.search" in capabilities
    assert all(item.read_only for item in capabilities.values())
