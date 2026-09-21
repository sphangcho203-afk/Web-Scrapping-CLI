from __future__ import annotations

from typing import Any

import pytest

from internet_hands.execution_meter import (
    execution_usage_snapshot,
    reset_execution_meter,
    start_execution_meter,
)
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
