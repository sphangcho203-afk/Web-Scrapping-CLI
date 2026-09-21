from __future__ import annotations

from types import SimpleNamespace

import pytest

from internet_hands import system_health


class _Mesh:
    async def provider_status(self):
        return {
            "nativeweb": {
                "configured": True,
                "searchable": True,
                "executable": True,
            },
            "firecrawl": {
                "configured": False,
                "searchable": True,
                "executable": False,
            },
        }


class _Registry:
    def __init__(self):
        self.capabilities = {
            "web.fetch.page": SimpleNamespace(
                id="web.fetch.page",
                candidates=(
                    SimpleNamespace(provider="firecrawl"),
                    SimpleNamespace(provider="nativeweb"),
                ),
            ),
            "vendor.only": SimpleNamespace(
                id="vendor.only",
                candidates=(SimpleNamespace(provider="firecrawl"),),
            ),
        }


@pytest.mark.asyncio
async def test_system_health_reports_provider_and_fallback_coverage(monkeypatch):
    async def authorized(_authorization):
        return None

    async def list_tools():
        return [
            SimpleNamespace(name=f"tool_{index}", input_schema={}, description="tool")
            for index in range(54)
        ]

    monkeypatch.setattr(system_health, "_scheduler_authorized", authorized)
    monkeypatch.setattr(system_health, "get_tool_mesh", lambda: _Mesh())
    monkeypatch.setattr(system_health, "get_capability_registry", lambda: _Registry())
    monkeypatch.setattr(
        system_health,
        "sandbox_mcp",
        SimpleNamespace(list_tools=list_tools),
    )

    result = await system_health.system_health("Bearer test", deep=False)
    assert result["status"] == "healthy"
    assert result["summary"]["provider_count"] == 2
    assert result["mcp"]["registered_tools"] == 54
    assert result["mcp"]["surface_ok"] is True
    assert result["summary"]["semantic_capabilities"] == 2
    assert result["summary"]["multi_provider_capabilities"] == 1
    assert result["fallbacks"]["native_web_provider"] == "nativeweb"
    assert result["fallbacks"]["single_provider_capabilities"] == ["vendor.only"]
