from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from internet_hands.catalog_providers import (
    HttpToolSpec,
    ManifestHttpProvider,
    OpenApiToolProvider,
    _OpenApiSource,
)


@pytest.mark.asyncio
async def test_manifest_provider_injects_secret_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_RAPID_KEY", "secret-value")
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"nickname": "Player"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ManifestHttpProvider(
        "rapidapi",
        [
            HttpToolSpec(
                tool_id="lookup",
                name="Lookup",
                description="Player lookup",
                method="GET",
                base_url="https://example.com",
                path="/lookup",
                parameters={
                    "id": {"in": "query", "required": True, "schema": {"type": "string"}}
                },
                requires_auth=True,
                auth_env="TEST_RAPID_KEY",
                auth_header="X-RapidAPI-Key",
                host_header="example.com",
            )
        ],
        client=client,
        validate_urls=False,
    )
    descriptor = await provider.describe("lookup")
    assert "secret-value" not in json.dumps(descriptor.to_dict())

    result = await provider.execute("lookup", {"id": "123"})
    assert result["status"] == "completed"
    assert result["data"]["nickname"] == "Player"
    assert seen["headers"]["x-rapidapi-key"] == "secret-value"
    assert seen["headers"]["x-rapidapi-host"] == "example.com"
    assert "id=123" in seen["url"]
    assert "secret-value" not in json.dumps(result)
    await client.aclose()


@pytest.mark.asyncio
async def test_openapi_provider_imports_and_executes_read_operations_only() -> None:
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Game API", "version": "1"},
        "servers": [{"url": "https://api.example.com/api"}],
        "paths": {
            "/heroes": {
                "get": {
                    "operationId": "listHeroes",
                    "summary": "List heroes",
                    "tags": ["heroes"],
                    "parameters": [
                        {
                            "name": "role",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string"},
                        }
                    ],
                },
                "post": {
                    "operationId": "createHero",
                    "summary": "Create hero",
                },
            },
            "/heroes/{hero}": {
                "get": {
                    "operationId": "getHero",
                    "summary": "Hero detail",
                    "parameters": [
                        {
                            "name": "hero",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                }
            },
        },
    }
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "spec.example.com":
            return httpx.Response(200, json=spec)
        return httpx.Response(200, json={"ok": True, "url": str(request.url)})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenApiToolProvider(
        [_OpenApiSource("game", "https://spec.example.com/openapi.json")],
        client=client,
        validate_urls=False,
    )

    rows = await provider.search("hero", limit=10)
    refs = {row.ref for row in rows}
    assert "openapi:game::listHeroes" in refs
    assert "openapi:game::getHero" in refs
    assert all("createHero" not in ref for ref in refs)

    detail = await provider.describe("game::getHero")
    assert detail.input_schema["required"] == ["hero"]
    result = await provider.execute("game::getHero", {"hero": "Lancelot"})
    assert result["status"] == "completed"
    assert any("/api/heroes/Lancelot" in url for url in seen)
    await client.aclose()


@pytest.mark.asyncio
async def test_manifest_provider_rejects_missing_required_argument() -> None:
    provider = ManifestHttpProvider(
        "publicapi",
        [
            HttpToolSpec(
                tool_id="lookup",
                name="Lookup",
                description="Lookup",
                method="GET",
                base_url="https://example.com",
                path="/lookup",
                parameters={"id": {"in": "query", "required": True}},
            )
        ],
        validate_urls=False,
    )
    with pytest.raises(ValueError, match="missing required arguments"):
        await provider.execute("lookup", {})
