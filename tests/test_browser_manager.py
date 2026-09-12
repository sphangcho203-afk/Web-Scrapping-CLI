from __future__ import annotations

import json
from typing import Any

import pytest

from internet_hands.browser_manager import BrowserSandboxManager
from internet_hands.browser_runtime import BROWSER_PACKAGE_PATH, BROWSER_RUNTIME_PATH
from internet_hands.sandbox_models import CommandResult, SandboxRef, SandboxSpec


class FakeBrowserProvider:
    def __init__(self) -> None:
        self.ready = False
        self.files: dict[tuple[str, str, str | None], bytes] = {}
        self.commands: list[tuple[str, str, list[str], dict[str, Any]]] = []
        self.started: list[tuple[str, str, list[str], dict[str, Any]]] = []

    async def create(self, spec: SandboxSpec) -> SandboxRef:
        return SandboxRef(spec.name, "sbx_test", "running")

    async def get(self, name: str, *, resume: bool = True) -> SandboxRef:
        return SandboxRef(name, "sbx_test", "running", raw={"resumed": resume})

    async def exec(
        self,
        session_id: str,
        command: str,
        args: list[str] | None = None,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        sudo: bool = False,
        timeout_ms: int = 30_000,
    ) -> CommandResult:
        args = args or []
        options = {
            "cwd": cwd,
            "env": env,
            "sudo": sudo,
            "timeout_ms": timeout_ms,
        }
        self.commands.append((session_id, command, args, options))
        if command == "pwd":
            return CommandResult(session_id, "cmd_pwd", 0, "/vercel/sandbox\n", "")
        if command == "test":
            return CommandResult(session_id, "cmd_test", 0 if self.ready else 1, "", "")
        if command == "node":
            request_path = args[-1]
            request_rel = request_path.removeprefix("/vercel/sandbox/")
            payload = json.loads(self.files[(session_id, request_rel, "/vercel/sandbox")])
            response = {
                "ok": True,
                "browser_session": payload["browser_session"],
                "state": {"url": "https://example.com", "title": "Example"},
                "action": payload["action"],
            }
            return CommandResult(
                session_id,
                "cmd_browser",
                0,
                json.dumps(response) + "\n",
                "",
            )
        return CommandResult(session_id, "cmd_other", 0, "", "")

    async def start(
        self,
        session_id: str,
        command: str,
        args: list[str] | None = None,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        sudo: bool = False,
        timeout_ms: int = 120_000,
    ) -> CommandResult:
        args = args or []
        options = {
            "cwd": cwd,
            "env": env,
            "sudo": sudo,
            "timeout_ms": timeout_ms,
        }
        self.started.append((session_id, command, args, options))
        return CommandResult(session_id, "cmd_prepare", None, "", "")

    async def write_file(
        self,
        session_id: str,
        path: str,
        content: bytes,
        *,
        cwd: str | None = None,
    ) -> None:
        self.files[(session_id, path, cwd)] = content

    async def read_file(
        self, session_id: str, path: str, *, cwd: str | None = None
    ) -> bytes:
        return self.files[(session_id, path, cwd)]

    async def command(
        self, session_id: str, command_id: str, *, wait: bool = False
    ) -> dict[str, Any]:
        return {"command": {"id": command_id, "wait": wait}}

    async def list_commands(self, session_id: str) -> list[dict[str, Any]]:
        return []

    async def command_logs(
        self, session_id: str, command_id: str, *, max_bytes: int = 1_000_000
    ) -> dict[str, Any]:
        return {"text": ""}

    async def kill_command(
        self, session_id: str, command_id: str, *, signal: int = 15
    ) -> dict[str, Any]:
        return {"killed": command_id, "signal": signal}

    async def snapshot(self, session_id: str) -> dict[str, object]:
        return {"snapshot": {"id": "snap_test"}}

    async def stop(self, session_id: str) -> dict[str, Any]:
        return {"stopped": session_id}

    async def delete(self, name: str) -> dict[str, Any]:
        return {"deleted": name}

    async def fork(
        self,
        source_name: str,
        new_name: str,
        *,
        ports: list[int] | None = None,
        timeout: str | None = None,
        vcpus: int | None = None,
        memory_mb: int | None = None,
        image: str | None = None,
        persistent: bool = True,
    ) -> SandboxRef:
        return SandboxRef(new_name, "sbx_fork", "running")


@pytest.mark.asyncio
async def test_browser_prepare_is_idempotent_and_backgrounded() -> None:
    provider = FakeBrowserProvider()
    manager = BrowserSandboxManager(provider)

    result = await manager.browser_prepare("sbx_test")
    assert result["ready"] is False
    assert result["process"]["command_id"] == "cmd_prepare"
    assert ("sbx_test", BROWSER_PACKAGE_PATH, "/vercel/sandbox") in provider.files
    assert ("sbx_test", BROWSER_RUNTIME_PATH, "/vercel/sandbox") in provider.files
    assert provider.started[-1][1] == "/bin/sh"
    assert "playwright install chromium" in provider.started[-1][2][-1]

    provider.ready = True
    again = await manager.browser_prepare("sbx_test")
    assert again["ready"] is True
    assert again["process"] is None


@pytest.mark.asyncio
async def test_browser_state_uses_versioned_runtime_and_cleans_request() -> None:
    provider = FakeBrowserProvider()
    provider.ready = True
    manager = BrowserSandboxManager(provider)

    result = await manager.browser_state(
        "sbx_test", browser_session="research", cwd="/vercel/sandbox/work"
    )
    assert result["ok"] is True
    assert result["browser_session"] == "research"
    assert result["action"] == "state"

    node = next(item for item in provider.commands if item[1] == "node")
    assert node[2][0].endswith("/.internet-hands/browser/runtime.mjs")
    assert node[3]["cwd"] == "/vercel/sandbox/work"
    assert any(item[1] == "rm" for item in provider.commands)


@pytest.mark.asyncio
async def test_browser_actions_validate_inputs_before_guest_execution() -> None:
    provider = FakeBrowserProvider()
    provider.ready = True
    manager = BrowserSandboxManager(provider)

    with pytest.raises(ValueError):
        await manager.browser_open("sbx_test", "http://localhost/admin")
    with pytest.raises(ValueError):
        await manager.browser_click("sbx_test", "")
    with pytest.raises(ValueError):
        await manager.browser_fill("sbx_test", "input", "x" * 100_001)
    with pytest.raises(ValueError):
        await manager.browser_capture("sbx_test", output_path="../escape.png")
    with pytest.raises(ValueError):
        await manager.browser_trace("sbx_test", kind="other")
