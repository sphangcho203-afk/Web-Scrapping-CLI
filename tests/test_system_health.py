from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse

from internet_hands import system_health


class _Mesh:
    discovery_timeout_seconds = 5
    provider_max_concurrency = 8

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


class _Reliability:
    def __init__(self):
        self.reset_calls = []

    def enabled(self):
        return True

    def shared_configured(self):
        return True

    def diagnostics(self):
        return {
            "enabled": True,
            "shared_configured": True,
            "shared_refresh_seconds": 15,
            "shared_last_refresh_at": 123.0,
            "shared_error": None,
        }

    def snapshot(self, provider=None):
        rows = {
            "nativeweb": {
                "provider": "nativeweb",
                "samples": 4,
                "successes": 4,
                "failures": 0,
                "score": 87,
                "circuit_open": False,
                "circuit_remaining_seconds": 0,
                "routing_penalty": 0,
                "scope": "runtime-local",
            },
            "firecrawl": {
                "provider": "firecrawl",
                "samples": 3,
                "successes": 0,
                "failures": 3,
                "score": 43,
                "circuit_open": True,
                "circuit_remaining_seconds": 30,
                "routing_penalty": 100000,
                "scope": "runtime-local",
            },
        }
        if provider is not None:
            return rows.get(
                provider,
                {
                    "provider": provider,
                    "samples": 0,
                    "successes": 0,
                    "failures": 0,
                    "score": 75,
                    "circuit_open": False,
                    "circuit_remaining_seconds": 0,
                    "routing_penalty": 0,
                    "scope": "runtime-local",
                },
            )
        return rows

    def reset(self, provider=None):
        self.reset_calls.append(provider)


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
        names = sorted(system_health._REQUIRED_MCP_TOOLS) + ["future_additive_tool"]
        return [
            SimpleNamespace(name=name, input_schema={}, description="tool")
            for name in names
        ]

    monkeypatch.setattr(system_health, "_scheduler_authorized", authorized)
    reliability = _Reliability()
    monkeypatch.setattr(system_health, "provider_reliability", reliability)
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
    assert result["mcp"]["registered_tools"] == len(system_health._REQUIRED_MCP_TOOLS) + 1
    assert result["mcp"]["surface_ok"] is True
    assert result["mcp"]["missing_required_tools"] == []
    assert result["mcp"]["extra_tools"] == ["future_additive_tool"]
    assert result["stability"]["provider_default_max_concurrency"] == 8
    assert result["summary"]["semantic_capabilities"] == 2
    assert result["summary"]["multi_provider_capabilities"] == 1
    assert result["summary"]["open_provider_circuits"] == 1
    assert result["summary"]["degraded_runtime_providers"] == 1
    assert result["providers"]["firecrawl"]["runtime_reliability"]["circuit_open"] is True
    assert result["fallbacks"]["native_web_provider"] == "nativeweb"
    assert "nativeweb:context" in result["fallbacks"]["native_web_tools"]
    assert result["fallbacks"]["adaptive_provider_routing"]["enabled"] is True
    assert result["fallbacks"]["adaptive_provider_routing"]["read_only_only"] is True
    assert result["fallbacks"]["adaptive_provider_routing"]["write_replay"] is False
    assert result["fallbacks"]["adaptive_provider_routing"]["scope"] == "runtime+shared"
    assert (
        result["fallbacks"]["adaptive_provider_routing"]["diagnostics"]["shared_configured"]
        is True
    )
    assert result["fallbacks"]["single_provider_capabilities"] == ["vendor.only"]



@pytest.mark.asyncio
async def test_strict_health_returns_503_when_degraded(monkeypatch):
    async def authorized(_authorization):
        return None

    async def list_tools():
        names = sorted(system_health._REQUIRED_MCP_TOOLS)[1:]
        return [
            SimpleNamespace(name=name, input_schema={}, description="tool")
            for name in names
        ]

    monkeypatch.setattr(system_health, "_scheduler_authorized", authorized)
    monkeypatch.setattr(system_health, "get_tool_mesh", lambda: _Mesh())
    monkeypatch.setattr(system_health, "get_capability_registry", lambda: _Registry())
    monkeypatch.setattr(
        system_health,
        "sandbox_mcp",
        SimpleNamespace(list_tools=list_tools),
    )

    result = await system_health.system_health("Bearer test", deep=False, strict=True)
    assert isinstance(result, JSONResponse)
    assert result.status_code == 503



@pytest.mark.asyncio
async def test_provider_reliability_status_and_reset_are_authorized(monkeypatch):
    async def authorized(_authorization):
        return None

    reliability = _Reliability()
    monkeypatch.setattr(system_health, "_scheduler_authorized", authorized)
    monkeypatch.setattr(system_health, "provider_reliability", reliability)

    status = await system_health.provider_reliability_status(
        "Bearer test",
        provider="firecrawl",
    )
    assert status["provider"]["provider"] == "firecrawl"
    assert status["provider"]["circuit_open"] is True

    reset = await system_health.provider_reliability_reset(
        "Bearer test",
        provider="firecrawl",
    )
    assert reset == {
        "ok": True,
        "provider": "firecrawl",
        "scope": "runtime+shared",
    }
    assert reliability.reset_calls == ["firecrawl"]



@pytest.mark.asyncio
async def test_deep_health_times_out_one_capability_without_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowRegistry:
        def __init__(self):
            self.capabilities = {
                "slow": SimpleNamespace(
                    id="slow",
                    candidates=(SimpleNamespace(provider="nativeweb"),),
                )
            }

        async def resolve(self, _capability_id):
            await __import__("asyncio").sleep(60)
            return {"resolved": []}

    monkeypatch.setenv("OPENCRAWL_HEALTH_CAPABILITY_TIMEOUT_SECONDS", "0.25")
    monkeypatch.setattr(
        system_health,
        "get_capability_registry",
        lambda: SlowRegistry(),
    )

    rows = await system_health._deep_capability_health(limit=1)

    assert rows == [
        {
            "id": "slow",
            "available": False,
            "error": "capability health check timed out",
            "error_class": "timeout",
        }
    ]
