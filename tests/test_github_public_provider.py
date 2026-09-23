from __future__ import annotations

import asyncio
import base64
import json

import pytest

from internet_hands.capability_economics import estimate_call, settle_measured_cost
from internet_hands.github_public_provider import (
    GitHubPublicProvider,
    PublicRepositoryError,
    repository_parts,
)


def test_only_public_github_repository_identifiers_are_accepted() -> None:
    assert repository_parts("https://github.com/example/project.git") == ("example", "project")
    for value in ("https://github.com.evil.test/example/project", "https://github.com/example/project/secret", "owner/../repo"):
        with pytest.raises(PublicRepositoryError):
            repository_parts(value)


def test_repository_search_and_spec_inspection_are_bounded_and_source_linked(monkeypatch) -> None:
    provider = GitHubPublicProvider()
    spec = {"openapi": "3.1.0", "paths": {"/heroes": {"get": {}}, "/players/{id}": {"get": {}}},
            "components": {"securitySchemes": {"oauth": {"flows": {"authorizationCode": {
                "scopes": {"player.read": "Read public player data"},
            }}}}}}

    async def get(path, *, params, calls):
        calls.append(path)
        if path == "/search/repositories":
            assert params["per_page"] == 10
            assert params["q"].endswith(" is:public")
            return {"items": [{"full_name": "sample/game-api", "html_url": "https://github.com/sample/game-api",
                               "license": {"spdx_id": "MIT"}}], "total_count": 1}
        if path == "/repos/sample/game-api":
            return {"full_name": "sample/game-api", "html_url": "https://github.com/sample/game-api",
                    "visibility": "public", "default_branch": "main", "license": {"spdx_id": "MIT"}}
        if path.endswith("/git/trees/main"):
            return {"tree": [{"type": "blob", "path": "docs/openapi.json", "size": 100},
                             {"type": "blob", "path": "src/routes/players.py", "size": 200},
                             {"type": "blob", "path": "assets/huge.bin", "size": 500_000}], "truncated": False}
        if path.endswith("/contents/docs/openapi.json"):
            return {"content": base64.b64encode(json.dumps(spec).encode()).decode()}
        raise AssertionError(path)

    monkeypatch.setattr(provider, "_get", get)
    searched = asyncio.run(provider.execute("search", {"query": "game api", "limit": 500}))
    assert searched["data"]["repositories"][0]["license"] == "MIT"
    inspected = asyncio.run(provider.execute("inspect", {"repository": "sample/game-api"}))
    data = inspected["data"]
    assert data["api_requests"] == 3
    assert data["api_specs"][0]["endpoints"][0] == {"method": "GET", "path": "/heroes"}
    assert data["api_specs"][0]["oauth_scopes"] == ["player.read"]
    assert not any("huge.bin" in row["path"] for row in data["candidate_files"])


def test_repository_measured_cost_is_capped_and_failed_work_releases_base() -> None:
    arguments = {"repository": "sample/game-api"}
    reserved = estimate_call("repo:inspect", arguments, "free").credits
    assert reserved == 7
    assert settle_measured_cost("repo:inspect", arguments, "free", reserved_credits=reserved,
                                execution_usage={"completed": True, "counters": {"github_api_calls": 3}}) == 4
    assert settle_measured_cost("repo:inspect", arguments, "free", reserved_credits=reserved,
                                execution_usage={"completed": False, "counters": {"github_api_calls": 0}}) == 0
