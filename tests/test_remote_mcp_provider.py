from __future__ import annotations

from dataclasses import dataclass

import pytest

from internet_hands.remote_mcp_provider import RemoteMcpToolProvider, _side_effecting


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
