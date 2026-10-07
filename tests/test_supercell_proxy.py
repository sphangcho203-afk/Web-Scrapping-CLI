from __future__ import annotations

import json

import httpx
import pytest

from internet_hands import gaming_providers, policy
from internet_hands.gaming_providers import (
    build_brawlstars_provider,
    build_clashofclans_provider,
    build_clashroyale_provider,
)

_GAMES = [
    ("BRAWL_STARS", build_brawlstars_provider, "api.brawlstars.com", "bsproxy.royaleapi.dev"),
    ("CLASH_OF_CLANS", build_clashofclans_provider, "api.clashofclans.com", "cocproxy.royaleapi.dev"),
    ("CLASH_ROYALE", build_clashroyale_provider, "api.clashroyale.com", "proxy.royaleapi.dev"),
]


@pytest.fixture(params=_GAMES, ids=[game[0] for game in _GAMES])
def game_config(request, monkeypatch: pytest.MonkeyPatch):
    for prefix, *_ in _GAMES:
        monkeypatch.delenv(prefix + "_AUTHORIZATION", raising=False)
        monkeypatch.delenv(prefix + "_USE_COMMUNITY_PROXY", raising=False)
    monkeypatch.setattr(gaming_providers, "supabase_vault_secret", lambda name: None)
    # Deterministic DNS while exercising the normal public-address policy.
    monkeypatch.setattr(policy, "_DNS_CACHE", {})
    monkeypatch.setattr(
        policy.socket, "getaddrinfo",
        lambda host, port, **kwargs: [(2, 1, 6, "", ("45.79.218.79", port))],
    )
    return request.param


@pytest.mark.asyncio
async def test_vault_key_routes_read_only_call_through_proxy_without_leaking_key(
    game_config, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix, build_provider, _, proxy_host = game_config
    monkeypatch.setenv(prefix + "_USE_COMMUNITY_PROXY", "true")
    monkeypatch.setenv(prefix + "_AUTHORIZATION", "Bearer older-env-key")
    seen_names: list[str] = []

    def vault(name: str) -> str:
        seen_names.append(name)
        return "vault-token"

    monkeypatch.setattr(gaming_providers, "supabase_vault_secret", vault)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == proxy_host
        assert request.url.raw_path == b"/v1/players/%23P0LY"
        assert request.headers["authorization"] == "Bearer vault-token"
        return httpx.Response(200, json={"tag": "#P0LY", "name": "Player"})

    provider = build_provider()
    status = await provider.status()
    assert status["configured_tools"] == len(provider.tools)
    assert all(status["tool_availability"].values())
    rows = await provider.search("", limit=10)
    assert all(row.metadata["configured"] for row in rows)
    assert all(not row.side_effecting for row in rows)
    descriptor = await provider.describe("player")
    assert descriptor.metadata["configured"] is True
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider.client = client
        result = await provider.execute("player", {
            "player_tag": "#P0LY", "authorization": "caller-token",
            "base_url": "https://attacker.example", "api_key": "caller-token",
        })
    assert result["data"]["tag"] == "#P0LY"
    assert result["metadata"]["host"] == proxy_host
    serialized = json.dumps([status, descriptor.to_dict(), result])
    assert "vault-token" not in serialized
    assert "older-env-key" not in serialized
    assert set(seen_names) == {prefix + "_API_KEY"}
    assert len(seen_names) == 4  # One resolution per discovery/execute, shared by all tools.


@pytest.mark.asyncio
@pytest.mark.parametrize("proxy_flag", [None, "false", "https://attacker.example"])
async def test_direct_api_remains_default_and_environment_header_still_works(
    game_config, monkeypatch: pytest.MonkeyPatch, proxy_flag: str | None,
) -> None:
    prefix, build_provider, official_host, _ = game_config
    if proxy_flag is not None:
        monkeypatch.setenv(prefix + "_USE_COMMUNITY_PROXY", proxy_flag)
    monkeypatch.setenv(prefix + "_AUTHORIZATION", "Bearer env-token")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == official_host
        assert request.headers["authorization"] == "Bearer env-token"
        return httpx.Response(200, json={"items": []})

    provider = build_provider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider.client = client
        await provider.execute("player", {"player_tag": "#P0LY"})


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, "Bearer ", "secret\r\nInjected:value", "非ASCII", "a b"])
async def test_missing_or_invalid_vault_credentials_stay_unavailable_and_send_nothing(
    game_config, monkeypatch: pytest.MonkeyPatch, value: str | None,
) -> None:
    prefix, build_provider, _, _ = game_config
    monkeypatch.setattr(gaming_providers, "supabase_vault_secret", lambda name: value)
    if value is not None:
        monkeypatch.setenv(prefix + "_AUTHORIZATION", "Bearer older-key")
    provider = build_provider()
    assert (await provider.status())["configured"] is False
    assert (await provider.describe("player")).metadata["configured"] is False
    with pytest.raises(RuntimeError, match=prefix + "_AUTHORIZATION is required"):
        await provider.execute("player", {"player_tag": "#P0LY"})


@pytest.mark.asyncio
async def test_proxy_failure_does_not_retry_token_on_direct_api(
    game_config, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix, build_provider, _, proxy_host = game_config
    monkeypatch.setenv(prefix + "_USE_COMMUNITY_PROXY", "true")
    monkeypatch.setattr(gaming_providers, "supabase_vault_secret", lambda name: "Bearer token")
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        assert request.headers["authorization"] == "Bearer token"
        return httpx.Response(403, json={"reason": "accessDenied"})

    provider = build_provider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider.client = client
        with pytest.raises(httpx.HTTPStatusError):
            await provider.execute("player", {"player_tag": "#P0LY"})
    assert seen == [proxy_host]


@pytest.mark.asyncio
async def test_proxy_still_rejects_private_dns_results(
    game_config, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix, build_provider, _, _ = game_config
    monkeypatch.setenv(prefix + "_USE_COMMUNITY_PROXY", "true")
    monkeypatch.setattr(gaming_providers, "supabase_vault_secret", lambda name: "token")
    monkeypatch.setattr(
        policy.socket, "getaddrinfo",
        lambda host, port, **kwargs: [(2, 1, 6, "", ("127.0.0.1", port))],
    )
    with pytest.raises(policy.PolicyError, match="non-public"):
        await build_provider().execute("player", {"player_tag": "#P0LY"})
