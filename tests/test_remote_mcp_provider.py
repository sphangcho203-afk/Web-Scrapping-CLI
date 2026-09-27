from __future__ import annotations

from dataclasses import dataclass

import pytest

from internet_hands.auth import current_auth
from internet_hands.control_store import AuthIdentity
from internet_hands.remote_mcp_provider import (
    RemoteMcpToolProvider,
    _normalize_headers,
    _side_effecting,
    _source_from_connection,
    parse_curl_connection,
)


@dataclass
class FakeTool:
    annotations: dict[str, object] | None

    def model_dump(self, *, mode: str = "json") -> dict[str, object]:
        assert mode == "json"
        return {"annotations": self.annotations}


def _identity(user_id: str = "usr_1") -> AuthIdentity:
    return AuthIdentity(
        user_id=user_id,
        api_key_id="key_1",
        scopes=["mcp:read", "mcp:execute"],
        plan_slug="pro",
        rpm_limit=120,
        source="api_key",
    )


def test_remote_mcp_unknown_tool_defaults_to_side_effecting() -> None:
    assert _side_effecting(FakeTool(None)) is True
    assert _side_effecting(FakeTool({})) is True


def test_remote_mcp_read_only_hint_is_respected() -> None:
    assert _side_effecting(FakeTool({"readOnlyHint": True})) is False
    assert _side_effecting(FakeTool({"read_only_hint": True})) is False
    assert _side_effecting(FakeTool({"readOnlyHint": False})) is True


def test_remote_mcp_sources_parse_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "INTERNET_HANDS_REMOTE_MCP_SOURCES",
        '[{"name":"research","url":"https://example.com/mcp"}]',
    )
    provider = RemoteMcpToolProvider(validate_urls=False)
    assert provider.sources[0].name == "research"
    assert provider.sources[0].url == "https://example.com/mcp"


def test_remote_mcp_source_config_requires_array(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNET_HANDS_REMOTE_MCP_SOURCES", '{"name":"wrong"}')
    with pytest.raises(TypeError):
        RemoteMcpToolProvider(validate_urls=False)


def test_remote_mcp_sources_support_api_key_and_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "INTERNET_HANDS_REMOTE_MCP_SOURCES",
        '[{"name":"private","url":"https://example.com/mcp","transport":"sse","auth_type":"api_key","header_name":"X-API-Key","secret":"top-secret"}]',
    )
    provider = RemoteMcpToolProvider(validate_urls=False)
    source = provider.sources[0]
    assert source.transport == "sse"
    assert source.auth_type == "api_key"
    assert source.requires_auth is True
    assert dict(source.headers)["X-API-Key"] == "top-secret"
    assert "top-secret" not in str(source.public_dict())


def test_saved_connection_builds_runtime_source_without_exposing_secret() -> None:
    source = _source_from_connection(
        {
            "id": "con_123",
            "name": "Private research",
            "endpoint_url": "https://example.com/mcp",
            "transport": "streamable_http",
            "auth_type": "bearer",
            "secret_config": {"headers": {"Authorization": "Bearer super-secret"}},
        }
    )
    assert source.name == "con_123"
    assert source.display_name == "Private research"
    assert source.connection_id == "con_123"
    assert dict(source.headers)["Authorization"] == "Bearer super-secret"
    assert "super-secret" not in str(source.public_dict())


@pytest.mark.asyncio
async def test_saved_connections_are_loaded_only_for_authenticated_user() -> None:
    calls: list[str] = []

    def loader(user_id: str) -> list[dict[str, object]]:
        calls.append(user_id)
        return [
            {
                "id": "con_abc",
                "name": "User MCP",
                "endpoint_url": "https://example.com/mcp",
                "transport": "streamable_http",
                "auth_type": "api_key",
                "secret_config": {"headers": {"X-API-Key": "secret-value"}},
            }
        ]

    provider = RemoteMcpToolProvider(
        sources=[], validate_urls=False, connection_loader=loader
    )
    anonymous = await provider.status()
    assert anonymous["source_count"] == 0
    assert calls == []

    token = current_auth.set(_identity("usr_owner"))
    try:
        authenticated = await provider.status()
    finally:
        current_auth.reset(token)

    assert calls == ["usr_owner"]
    assert authenticated["source_count"] == 1
    assert authenticated["user_source_count"] == 1
    assert authenticated["sources"][0]["connection_id"] == "con_abc"
    assert authenticated["sources"][0]["header_names"] == ["X-API-Key"]
    assert "secret-value" not in str(authenticated)


@pytest.mark.asyncio
async def test_saved_connections_do_not_cross_user_contexts() -> None:
    def loader(user_id: str) -> list[dict[str, object]]:
        return [
            {
                "id": f"con_{user_id}",
                "name": f"MCP for {user_id}",
                "endpoint_url": "https://example.com/mcp",
                "transport": "streamable_http",
                "auth_type": "none",
                "secret_config": {},
            }
        ]

    provider = RemoteMcpToolProvider(
        sources=[], validate_urls=False, connection_loader=loader
    )
    token = current_auth.set(_identity("alice"))
    try:
        alice = await provider.status()
    finally:
        current_auth.reset(token)
    token = current_auth.set(_identity("bob"))
    try:
        bob = await provider.status()
    finally:
        current_auth.reset(token)

    assert alice["sources"][0]["connection_id"] == "con_alice"
    assert bob["sources"][0]["connection_id"] == "con_bob"


def test_outbound_mcp_headers_reject_hop_by_hop_and_newlines() -> None:
    with pytest.raises(ValueError, match="unsafe outbound MCP header"):
        _normalize_headers({"Host": "attacker.example"})
    with pytest.raises(ValueError, match="invalid newline"):
        _normalize_headers({"Authorization": "Bearer good\r\nX-Evil: yes"})


def test_parse_curl_connection_detects_bearer_and_redacts_nothing_itself() -> None:
    draft = parse_curl_connection(
        "curl -X POST https://example.com/mcp -H 'Authorization: Bearer abc123' -H 'Accept: application/json'"
    )
    assert draft["url"] == "https://example.com/mcp"
    assert draft["auth_type"] == "bearer"
    assert draft["headers"]["Authorization"] == "Bearer abc123"


@pytest.mark.parametrize("flag", ["-u", "--user", "--cookie", "-b", "--cert", "--key"])
def test_parse_curl_connection_rejects_credential_file_and_basic_auth_flags(flag: str) -> None:
    with pytest.raises(ValueError, match="unsupported credential-bearing"):
        parse_curl_connection(f"curl https://example.com/mcp {flag} secret")
