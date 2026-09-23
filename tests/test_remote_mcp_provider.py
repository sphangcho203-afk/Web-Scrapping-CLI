from __future__ import annotations

from dataclasses import dataclass

import pytest

from internet_hands.remote_mcp_provider import (
    RemoteMcpToolProvider,
    _side_effecting,
    parse_curl_connection,
)


@dataclass
class FakeTool:
    annotations: dict[str, object] | None

    def model_dump(self, *, mode: str = "json") -> dict[str, object]:
        assert mode == "json"
        return {"annotations": self.annotations}


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


def test_parse_curl_connection_detects_bearer_and_redacts_nothing_itself() -> None:
    draft = parse_curl_connection(
        "curl -X POST https://example.com/mcp -H 'Authorization: Bearer abc123' -H 'Accept: application/json'"
    )
    assert draft["url"] == "https://example.com/mcp"
    assert draft["auth_type"] == "bearer"
    assert draft["headers"]["Authorization"] == "Bearer abc123"


@pytest.mark.parametrize("flag", ["-u", "--user", "--cookie", "--cert", "--key"])
def test_parse_curl_connection_rejects_credential_file_and_basic_auth_flags(flag: str) -> None:
    with pytest.raises(ValueError, match="unsupported credential-bearing"):
        parse_curl_connection(f"curl https://example.com/mcp {flag} secret")
