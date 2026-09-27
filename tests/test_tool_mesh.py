from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from internet_hands.execution_meter import (
    execution_usage_snapshot,
    reset_execution_meter,
    start_execution_meter,
)
from internet_hands.provider_reliability import provider_reliability
from internet_hands.tool_mesh import ToolDescriptor, ToolMesh


class FakeProvider:
    def __init__(self, name: str, prefix: str) -> None:
        self.name = name
        self.prefix = prefix

    async def status(self) -> dict[str, Any]:
        return {"configured": True}

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                ref=f"{self.name}:{self.prefix}{index}",
                provider=self.name,
                tool_id=f"{self.prefix}{index}",
                name=f"{query} {self.prefix}{index}",
            )
            for index in range(limit)
        ]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        return ToolDescriptor(
            ref=f"{self.name}:{tool_id}",
            provider=self.name,
            tool_id=tool_id,
            name=tool_id,
        )

    async def execute(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        account: str | None = None,
        wait_seconds: int = 30,
        timeout_seconds: int = 60,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "completed",
            "data": {
                "tool_id": tool_id,
                "arguments": arguments,
                "account": account,
                "wait_seconds": wait_seconds,
                "timeout_seconds": timeout_seconds,
                "options": options or {},
            },
        }

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        return {"id": job_id, "wait_seconds": wait_seconds, "status": "SUCCEEDED"}

    async def result_page(
        self, result_id: str, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        return {"result_id": result_id, "offset": offset, "limit": limit, "items": []}


@pytest.mark.asyncio
async def test_search_interleaves_providers() -> None:
    mesh = ToolMesh([FakeProvider("one", "a"), FakeProvider("two", "b")])
    result = await mesh.search("maps", limit=4)
    assert [tool["provider"] for tool in result["tools"]] == ["one", "two", "one", "two"]


@pytest.mark.asyncio
async def test_execute_and_dry_run() -> None:
    mesh = ToolMesh([FakeProvider("one", "a")])
    result = await mesh.execute("one:a0", {"x": 1}, account="work")
    assert result["status"] == "completed"
    assert result["data"]["arguments"] == {"x": 1}
    assert result["data"]["account"] == "work"

    preview = await mesh.execute("one:a0", {"x": 2}, dry_run=True)
    assert preview["status"] == "dry_run"
    assert preview["data"]["tool"]["ref"] == "one:a0"


@pytest.mark.asyncio
async def test_batch_preserves_input_order() -> None:
    mesh = ToolMesh([FakeProvider("one", "a")])
    result = await mesh.batch_execute(
        [
            {"ref": "one:a0", "arguments": {"n": 0}},
            {"ref": "one:a1", "arguments": {"n": 1}},
        ]
    )
    assert [item["index"] for item in result["results"]] == [0, 1]
    assert [item["data"]["arguments"]["n"] for item in result["results"]] == [0, 1]


@pytest.mark.asyncio
async def test_mesh_policy_blocks_denied_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNET_HANDS_TOOL_DENY", "one:a*")
    mesh = ToolMesh([FakeProvider("one", "a")])
    result = await mesh.search("x", limit=3)
    assert result["tools"] == []
    with pytest.raises(PermissionError):
        await mesh.execute("one:a0", {})



@pytest.mark.asyncio
async def test_execute_records_provider_call_but_dry_run_does_not() -> None:
    mesh = ToolMesh([FakeProvider("one", "a")])
    token = start_execution_meter()
    try:
        await mesh.execute("one:a0", {"x": 1})
        after_execute = execution_usage_snapshot()
        assert after_execute["provider_calls"]["one"] == 1

        await mesh.execute("one:a0", {"x": 2}, dry_run=True)
        after_dry_run = execution_usage_snapshot()
        assert after_dry_run["provider_calls"]["one"] == 1
    finally:
        reset_execution_meter(token)


def test_default_tool_mesh_registers_caller_research_provider() -> None:
    from internet_hands.tool_mcp import get_tool_mesh
    get_tool_mesh.cache_clear()
    assert "callerresearch" in get_tool_mesh().providers


@pytest.mark.asyncio
async def test_default_capability_registry_exposes_deep_caller_investigation() -> None:
    from internet_hands.tool_mcp import get_capability_registry, get_tool_mesh
    get_tool_mesh.cache_clear()
    get_capability_registry.cache_clear()
    registry = get_capability_registry()
    capability = registry.capabilities["phone.caller.investigate"]
    assert capability.pack == "phone"
    assert capability.read_only is True
    resolved = await registry.resolve("phone.caller.investigate")
    assert resolved["resolved"][0]["ref"] == "callerresearch:investigate"



@pytest.mark.asyncio
async def test_tool_mesh_records_real_provider_success_but_not_dry_run() -> None:
    provider_reliability.reset("one")
    try:
        mesh = ToolMesh([FakeProvider("one", "a")])
        await mesh.execute("one:a0", {"x": 1})
        after_success = provider_reliability.snapshot("one")
        assert after_success["successes"] == 1
        assert after_success["failures"] == 0

        await mesh.execute("one:a0", {"x": 2}, dry_run=True)
        after_dry_run = provider_reliability.snapshot("one")
        assert after_dry_run["successes"] == 1
        assert after_dry_run["neutral"] == 0
    finally:
        provider_reliability.reset("one")


@pytest.mark.asyncio
async def test_tool_mesh_records_provider_exception_as_failure() -> None:
    class BrokenProvider(FakeProvider):
        async def execute(self, *args, **kwargs):
            raise RuntimeError("upstream exploded")

    provider_reliability.reset("broken")
    try:
        mesh = ToolMesh([BrokenProvider("broken", "x")])
        result = await mesh.execute("broken:x0", {})

        assert result["status"] == "failed"
        state = provider_reliability.snapshot("broken")
        assert state["failures"] == 1
        assert state["last_error"] == "upstream exploded"
    finally:
        provider_reliability.reset("broken")



class RetryProvider(FakeProvider):
    def __init__(
        self,
        name: str,
        prefix: str,
        *,
        statuses: list[int | str],
        side_effecting: bool = False,
    ) -> None:
        super().__init__(name, prefix)
        self.statuses = list(statuses)
        self.execute_calls = 0
        self.side_effecting = side_effecting

    async def describe(self, tool_id: str) -> ToolDescriptor:
        descriptor = await super().describe(tool_id)
        descriptor.side_effecting = self.side_effecting
        return descriptor

    async def execute(self, tool_id: str, arguments: dict[str, Any], **kwargs):
        self.execute_calls += 1
        state = self.statuses.pop(0) if self.statuses else "completed"
        if isinstance(state, int):
            request = httpx.Request("GET", "https://provider.example/tool")
            response = httpx.Response(state, request=request)
            raise httpx.HTTPStatusError(
                f"provider returned {state}",
                request=request,
                response=response,
            )
        if state == "error":
            return {"status": "error", "error": "invalid request"}
        return await super().execute(tool_id, arguments, **kwargs)


@pytest.mark.asyncio
async def test_read_only_transient_failure_retries_and_meters_every_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setenv("OPENCRAWL_PROVIDER_READ_RETRIES", "1")
    monkeypatch.setattr("internet_hands.tool_mesh.asyncio.sleep", no_sleep)
    provider_reliability.reset("retry")
    provider = RetryProvider("retry", "x", statuses=[503, "completed"])
    mesh = ToolMesh([provider])
    token = start_execution_meter()
    try:
        result = await mesh.execute("retry:x0", {"q": "hello"})
        usage = execution_usage_snapshot()
    finally:
        reset_execution_meter(token)
        provider_reliability.reset("retry")

    assert result["status"] == "completed"
    assert provider.execute_calls == 2
    assert usage["provider_calls"]["retry"] == 2
    assert [row["status"] for row in usage["provider_events"]] == [
        "failed",
        "completed",
    ]
    assert usage["provider_events"][0]["error_class"] == "upstream_unavailable"
    assert usage["provider_events"][0]["retryable"] is True
    assert [row["attempt"] for row in result["metadata"]["provider_attempts"]] == [1, 2]


@pytest.mark.asyncio
async def test_auth_failure_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_READ_RETRIES", "3")
    provider = RetryProvider("authfail", "x", statuses=[401, "completed"])
    mesh = ToolMesh([provider])

    result = await mesh.execute("authfail:x0", {})

    assert result["status"] == "failed"
    assert provider.execute_calls == 1
    assert result["metadata"]["failure"]["category"] == "auth"
    assert result["metadata"]["provider_attempts"][0]["retryable"] is False


@pytest.mark.asyncio
async def test_side_effecting_tool_never_retries_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_READ_RETRIES", "3")
    provider = RetryProvider(
        "writer",
        "x",
        statuses=[503, "completed"],
        side_effecting=True,
    )
    mesh = ToolMesh([provider])

    result = await mesh.execute("writer:x0", {"message": "hello"})

    assert result["status"] == "failed"
    assert provider.execute_calls == 1
    assert result["metadata"]["failure"]["category"] == "upstream_unavailable"


@pytest.mark.asyncio
async def test_provider_error_status_is_normalized_to_failed_without_retry() -> None:
    provider = RetryProvider("errstatus", "x", statuses=["error"])
    mesh = ToolMesh([provider])

    result = await mesh.execute("errstatus:x0", {})

    assert result["status"] == "failed"
    assert provider.execute_calls == 1
    assert result["metadata"]["failure"]["category"] == "invalid_request"



def test_default_tool_mesh_registers_search_and_game_catalog_providers() -> None:
    from internet_hands.tool_mcp import get_capability_registry, get_tool_mesh

    get_tool_mesh.cache_clear()
    get_capability_registry.cache_clear()
    mesh = get_tool_mesh()
    registry = get_capability_registry()

    assert {"you", "rawg", "igdb"}.issubset(mesh.providers)
    assert {
        "web.search.news",
        "web.research.synthesized",
        "web.search.developer",
        "games.catalog.search",
        "games.platform.search",
    }.issubset(registry.capabilities)



@pytest.mark.asyncio
async def test_provider_status_timeout_is_isolated() -> None:
    class HangingStatusProvider(FakeProvider):
        async def status(self) -> dict[str, Any]:
            await asyncio.sleep(60)
            return {"configured": True}

    mesh = ToolMesh([HangingStatusProvider("slow-status", "x")])
    mesh.discovery_timeout_seconds = 0.01

    result = await mesh.provider_status()

    assert result["slow-status"]["configured"] is False
    assert result["slow-status"]["error_class"] == "timeout"
    assert result["slow-status"]["error"] == "provider status timed out"


@pytest.mark.asyncio
async def test_provider_search_timeout_does_not_block_other_catalogs() -> None:
    class HangingSearchProvider(FakeProvider):
        async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
            await asyncio.sleep(60)
            return []

    mesh = ToolMesh(
        [
            HangingSearchProvider("slow-search", "s"),
            FakeProvider("fast-search", "f"),
        ]
    )
    mesh.discovery_timeout_seconds = 0.01

    result = await mesh.search("maps", limit=2)

    assert result["errors"]["slow-search"] == "provider search timed out"
    assert [tool["provider"] for tool in result["tools"]] == [
        "fast-search",
        "fast-search",
    ]


@pytest.mark.asyncio
async def test_provider_bulkhead_limits_parallel_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CountingProvider(FakeProvider):
        def __init__(self, name: str, prefix: str) -> None:
            super().__init__(name, prefix)
            self.active = 0
            self.max_active = 0

        async def execute(self, tool_id: str, arguments: dict[str, Any], **kwargs):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(0.02)
                return await super().execute(tool_id, arguments, **kwargs)
            finally:
                self.active -= 1

    monkeypatch.setenv("OPENCRAWL_PROVIDER_MAX_CONCURRENCY_COUNTED", "2")
    provider = CountingProvider("counted", "x")
    mesh = ToolMesh([provider])

    result = await mesh.batch_execute(
        [
            {"ref": f"counted:x{index}", "arguments": {"n": index}}
            for index in range(6)
        ],
        max_concurrency=6,
    )

    assert all(row["status"] == "completed" for row in result["results"])
    assert provider.max_active == 2


@pytest.mark.asyncio
async def test_retry_delay_never_extends_past_execution_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_READ_RETRIES", "3")
    monkeypatch.setenv("OPENCRAWL_PROVIDER_RETRY_BASE_MS", "5000")
    monkeypatch.setenv("OPENCRAWL_PROVIDER_RETRY_MAX_WAIT_MS", "5000")
    provider = RetryProvider("deadline", "x", statuses=[503, "completed"])
    mesh = ToolMesh([provider])

    result = await mesh.execute("deadline:x0", {}, timeout_seconds=1)

    assert result["status"] == "failed"
    assert provider.execute_calls == 1
    assert result["metadata"]["failure"]["category"] == "upstream_unavailable"
    assert result["metadata"]["provider_attempts"][0]["retry_delay_seconds"] == 5.0
