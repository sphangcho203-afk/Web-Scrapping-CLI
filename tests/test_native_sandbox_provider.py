from __future__ import annotations

from typing import Any

import pytest

from internet_hands.native_sandbox_provider import NativeSandboxToolProvider


class FakeManager:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.started: list[tuple[str, str]] = []

    async def create(self, name: str, **_kwargs: Any) -> dict[str, Any]:
        return {"name": name, "session_id": "sbx_test"}

    async def shell(self, session_id: str, script: str, **_kwargs: Any) -> dict[str, Any]:
        assert session_id == "sbx_test"
        assert script == "printf ok"
        return {
            "session_id": session_id,
            "command_id": "cmd_1",
            "exit_code": 0,
            "stdout": "ok",
            "stderr": "",
            "events": [],
        }

    async def start(
        self, session_id: str, command: str, args: list[str], **_kwargs: Any
    ) -> dict[str, Any]:
        self.started.append((session_id, command))
        return {
            "session_id": session_id,
            "command_id": "cmd_bg",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "events": [],
        }

    async def delete(self, name: str) -> dict[str, Any]:
        self.deleted.append(name)
        return {"name": name, "deleted": True}


@pytest.mark.asyncio
async def test_native_sandbox_status_is_ready_with_injected_manager() -> None:
    provider = NativeSandboxToolProvider(FakeManager())
    status = await provider.status()
    assert status["configured"] is True
    assert status["executable"] is True


@pytest.mark.asyncio
async def test_native_sandbox_foreground_executes_and_cleans_up() -> None:
    manager = FakeManager()
    provider = NativeSandboxToolProvider(manager)
    result = await provider.execute("exec", {"command": "printf ok"})

    assert result["status"] == "completed"
    assert result["data"]["stdout"] == "ok"
    assert len(manager.deleted) == 1


@pytest.mark.asyncio
async def test_native_sandbox_background_returns_cleanup_handle() -> None:
    manager = FakeManager()
    provider = NativeSandboxToolProvider(manager)
    result = await provider.execute(
        "exec",
        {"command": "sleep 10", "background": True},
    )

    assert result["status"] == "running"
    assert result["job_id"] == "cmd_bg"
    assert result["data"]["cleanup_required"] is True
    assert manager.deleted == []


@pytest.mark.asyncio
async def test_native_sandbox_rejects_restart_semantics() -> None:
    provider = NativeSandboxToolProvider(FakeManager())
    with pytest.raises(ValueError, match="restart"):
        await provider.execute(
            "exec",
            {"command": "printf ok", "restart": True},
        )


@pytest.mark.asyncio
async def test_native_sandbox_descriptor_is_side_effecting() -> None:
    descriptor = await NativeSandboxToolProvider(FakeManager()).describe("exec")
    assert descriptor.side_effecting is True
    assert descriptor.metadata["configured"] is True
