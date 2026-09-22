from __future__ import annotations

import asyncio
import httpx
import pytest

from internet_hands.capability_packs import Capability, CapabilityCandidate
from internet_hands.catalog_providers import HttpToolSpec, ManifestHttpProvider, OpenApiToolProvider, _OpenApiSource
from internet_hands.game_execution import discover_game_tools, validate_game_arguments
from internet_hands.tool_mesh import ToolMesh


def test_curated_game_operation_runs_with_real_mesh_after_preflight() -> None:
    async def run():
        requests = []

        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"hero": request.url.params.get("hero")})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = ManifestHttpProvider("publicapi", [HttpToolSpec(
                tool_id="hero", name="Hero detail", description="Public hero detail", method="GET",
                base_url="https://public.example", path="/heroes",
                parameters={"hero": {"required": True, "schema": {"type": "string"}}},
            )], client=client, validate_urls=False)
            mesh = ToolMesh([provider])
            cap = Capability("mlbb.hero.detail", "Hero detail", "", "mlbb", (),
                             (CapabilityCandidate("publicapi", ref="publicapi:hero"),))
            options = await discover_game_tools(cap, mesh)
            assert [item["ref"] for item in options["tools"]] == ["publicapi:hero"]
            args = validate_game_arguments(options["tools"][0], {"hero": "Fanny"})
            execution = await mesh.execute("publicapi:hero", args)
            assert execution["status"] == "completed"
            assert execution["data"] == {"hero": "Fanny"}
            assert len(requests) == 1 and requests[0].method == "GET"
            with pytest.raises(ValueError, match="Unknown arguments"):
                validate_game_arguments(options["tools"][0], {"hero": "Fanny", "url": "http://localhost"})
    asyncio.run(run())


def test_discovery_excludes_auth_and_unrelated_operations() -> None:
    async def run():
        spec = {"openapi": "3.0.0", "security": [{"Bearer": []}], "servers": [{"url": "https://arena.example"}], "paths": {
            "/api/academy/items": {"get": {"summary": "Items", "operationId": "items", "tags": ["academy"], "security": []}},
            "/api/users/profile": {"get": {"summary": "My profile", "operationId": "profile", "tags": ["academy"], "security": [{"Bearer": []}]}},
            "/api/academy/heroes": {"get": {"summary": "Heroes", "operationId": "heroes", "tags": ["academy"], "security": []}},
            "/api/academy/items/update": {"post": {"summary": "Change items", "operationId": "update", "tags": ["academy"]}},
        }}

        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=spec)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = OpenApiToolProvider([_OpenApiSource("rone-mlbb", "https://arena.example/openapi.json")],
                                           client=client, validate_urls=False)
            mesh = ToolMesh([provider])
            cap = Capability("mlbb.academy.items", "Items", "", "mlbb", (),
                             (CapabilityCandidate("openapi", search="rone-mlbb academy items"),))
            options = await discover_game_tools(cap, mesh)
            assert [item["ref"] for item in options["tools"]] == ["openapi:rone-mlbb::items"]
            assert all(item["metadata"]["method"] == "GET" for item in options["tools"])
            with pytest.raises(ValueError, match="Header arguments"):
                validate_game_arguments({"input_schema": {"properties": {"Authorization": {"type": "string", "x-in": "header"}}}},
                                        {"Authorization": "secret"})
    asyncio.run(run())


def test_credential_locked_and_write_capabilities_are_not_exposed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run():
        monkeypatch.delenv("GAME_TEST_TOKEN", raising=False)
        provider = ManifestHttpProvider("publicapi", [HttpToolSpec(
            tool_id="rank", name="Private rank", description="", method="GET",
            base_url="https://public.example", path="/rank", auth_env="GAME_TEST_TOKEN",
        )], validate_urls=False)
        mesh = ToolMesh([provider])
        cap = Capability("mlbb.rank", "Rank", "", "mlbb", (),
                         (CapabilityCandidate("publicapi", ref="publicapi:rank"),))
        assert (await discover_game_tools(cap, mesh))["tools"] == []
        assert (await discover_game_tools(Capability("mlbb.write", "Write", "", "mlbb", (),
                                                cap.candidates, read_only=False), mesh))["tools"] == []
    asyncio.run(run())

