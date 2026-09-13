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
        self.daemon_alive = False
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
        if command == "node" and len(args) >= 3 and args[1] == "ping":
            return CommandResult(
                session_id,
                "cmd_ping",
                0 if self.daemon_alive else 1,
                '{"ok":true}\n' if self.daemon_alive else "",
                "" if self.daemon_alive else "ECONNREFUSED",
            )
        if command == "node" and len(args) >= 4 and args[1] == "client":
            request_path = args[3]
            request_rel = request_path.removeprefix("/vercel/sandbox/")
            payload = json.loads(self.files[(session_id, request_rel, "/vercel/sandbox")])
            if payload["action"] == "close":
                self.daemon_alive = False
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
        if command == "node" and len(args) >= 3 and args[1] == "daemon":
            self.daemon_alive = True
            return CommandResult(session_id, "cmd_daemon", None, "", "")
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
async def test_browser_prepare_is_versioned_and_backgrounded() -> None:
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
async def test_browser_state_starts_live_daemon_and_cleans_request() -> None:
    provider = FakeBrowserProvider()
    provider.ready = True
    manager = BrowserSandboxManager(provider)

    result = await manager.browser_state(
        "sbx_test", browser_session="research", cwd="work"
    )
    assert result["ok"] is True
    assert result["browser_session"] == "research"
    assert result["action"] == "state"
    assert result["daemon"]["command_id"] == "cmd_daemon"
    assert provider.daemon_alive is True

    daemon = next(item for item in provider.started if item[1] == "node")
    assert daemon[2][1:] == ["daemon", "research"]
    client = next(
        item for item in provider.commands if item[1] == "node" and len(item[2]) >= 2 and item[2][1] == "client"
    )
    assert client[3]["cwd"] == "/vercel/sandbox"
    request_files = [
        value
        for (sid, path, cwd), value in provider.files.items()
        if sid == "sbx_test" and "/requests/" in path and cwd == "/vercel/sandbox"
    ]
    assert request_files
    assert json.loads(request_files[-1])["cwd"] == "work"
    assert any(item[1] == "rm" for item in provider.commands)


@pytest.mark.asyncio
async def test_browser_calls_reuse_same_live_daemon_and_close_it() -> None:
    provider = FakeBrowserProvider()
    provider.ready = True
    manager = BrowserSandboxManager(provider)

    await manager.browser_fill("sbx_test", "input[name=q]", "hello", browser_session="qa")
    await manager.browser_press("sbx_test", "input[name=q]", "Enter", browser_session="qa")
    daemons = [
        item
        for item in provider.started
        if item[1] == "node" and len(item[2]) >= 2 and item[2][1] == "daemon"
    ]
    assert len(daemons) == 1
    assert provider.daemon_alive is True

    closed = await manager.browser_close("sbx_test", browser_session="qa")
    assert closed["ok"] is True
    assert closed["action"] == "close"
    assert provider.daemon_alive is False


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
    with pytest.raises(ValueError):
        await manager.browser_trace("sbx_test", max_events=201)
