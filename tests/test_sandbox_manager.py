from __future__ import annotations

import hashlib

import pytest

from internet_hands.sandbox_manager import SandboxManager
from internet_hands.sandbox_models import CommandResult, SandboxRef, SandboxSpec
from internet_hands.sandbox_policy import PUBLIC_NETWORK_DENY_CIDRS, public_network_policy


class FakeProvider:
    def __init__(self) -> None:
        self.created: SandboxSpec | None = None
        self.commands: list[tuple[str, str, list[str], dict[str, object]]] = []
        self.started: list[tuple[str, str, list[str], dict[str, object]]] = []
        self.files: dict[tuple[str, str], bytes] = {}
        self.routes: list[dict[str, object]] = [
            {"port": 3000, "url": "https://workbench-3000.example"}
        ]
        self.kills: list[tuple[str, str, int]] = []
        self.stopped: list[str] = []
        self.deleted: list[str] = []
        self.forked: list[tuple[str, str, dict[str, object]]] = []

    async def create(self, spec: SandboxSpec) -> SandboxRef:
        self.created = spec
        routes = [
            {"port": port, "url": f"https://{spec.name}-{port}.example"}
            for port in spec.ports
        ]
        return SandboxRef(spec.name, "sbx_test", "running", routes=routes)

    async def get(self, name: str, *, resume: bool = True) -> SandboxRef:
        return SandboxRef(
            name,
            "sbx_test",
            "running",
            routes=[dict(item) for item in self.routes],
            raw={"resumed": resume},
        )

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
        self.commands.append(
            (
                session_id,
                command,
                args or [],
                {"cwd": cwd, "env": env, "sudo": sudo, "timeout_ms": timeout_ms},
            )
        )
        return CommandResult(session_id, "cmd_test", 0, "ok", "")

    async def start(
        self,
        session_id: str,
        command: str,
        args: list[str] | None = None,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        sudo: bool = False,
        timeout_ms: int = 1_800_000,
    ) -> CommandResult:
        self.started.append(
            (
                session_id,
                command,
                args or [],
                {"cwd": cwd, "env": env, "sudo": sudo, "timeout_ms": timeout_ms},
            )
        )
        return CommandResult(session_id, "cmd_bg", None, "", "")

    async def command(
        self,
        session_id: str,
        command_id: str,
        *,
        wait: bool = False,
    ) -> dict[str, object]:
        return {
            "command": {"id": command_id, "sessionId": session_id, "exitCode": None},
            "wait": wait,
        }

    async def list_commands(self, session_id: str) -> list[dict[str, object]]:
        return [{"id": "cmd_bg", "sessionId": session_id, "exitCode": None}]

    async def command_logs(
        self,
        session_id: str,
        command_id: str,
        *,
        max_bytes: int = 1_000_000,
    ) -> dict[str, object]:
        return {
            "session_id": session_id,
            "command_id": command_id,
            "text": "server ready",
            "bytes": min(12, max_bytes),
            "truncated": False,
        }

    async def kill_command(
        self,
        session_id: str,
        command_id: str,
        *,
        signal: int = 15,
    ) -> dict[str, object]:
        self.kills.append((session_id, command_id, signal))
        return {"command": {"id": command_id}, "signal": signal}

    async def read_file(
        self, session_id: str, path: str, *, cwd: str | None = None
    ) -> bytes:
        return self.files[(session_id, path)]

    async def write_file(
        self,
        session_id: str,
        path: str,
        content: bytes,
        *,
        cwd: str | None = None,
    ) -> None:
        self.files[(session_id, path)] = content

    async def snapshot(self, session_id: str) -> dict[str, object]:
        return {"snapshot": {"id": "snap_test", "sourceSessionId": session_id}}

    async def stop(self, session_id: str) -> dict[str, object]:
        self.stopped.append(session_id)
        return {"session": {"id": session_id, "status": "stopped"}}

    async def delete(self, name: str) -> dict[str, object]:
        self.deleted.append(name)
        return {"name": name, "deleted": True}

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
        options: dict[str, object] = {
            "ports": ports or [],
            "timeout": timeout or "",
            "vcpus": vcpus or 0,
            "memory_mb": memory_mb or 0,
            "image": image or "",
            "persistent": persistent,
        }
        self.forked.append((source_name, new_name, options))
        routes = [
            {"port": port, "url": f"https://{new_name}-{port}.example"}
            for port in ports or []
        ]
        return SandboxRef(new_name, "sbx_fork", "running", routes=routes)


@pytest.mark.asyncio
async def test_create_validates_resources_and_ports() -> None:
    provider = FakeProvider()
    manager = SandboxManager(provider)
    result = await manager.create(
        "workbench", vcpus=2, memory_mb=2048, ports=[3000, 3000]
    )
    assert result["session_id"] == "sbx_test"
    assert provider.created is not None
    assert provider.created.ports == [3000]

    with pytest.raises(ValueError):
        await manager.create("bad name")
    with pytest.raises(ValueError):
        await manager.create("ok", vcpus=99)


@pytest.mark.asyncio
async def test_exec_enforces_timeout_policy() -> None:
    provider = FakeProvider()
    manager = SandboxManager(provider)
    result = await manager.exec("sbx_test", "python", ["-V"], timeout_ms=10_000)
    assert result["exit_code"] == 0
    assert provider.commands[-1][1] == "python"

    with pytest.raises(ValueError):
        await manager.exec("sbx_test", "sleep", ["999"], timeout_ms=999_999)


@pytest.mark.asyncio
async def test_detached_process_control_and_logs() -> None:
    provider = FakeProvider()
    manager = SandboxManager(provider)
    result = await manager.start(
        "sbx_test", "python", ["-m", "http.server", "3000"]
    )
    assert result["command_id"] == "cmd_bg"
    assert provider.started[-1][3]["timeout_ms"] == 1_800_000

    status = await manager.command("sbx_test", "cmd_bg")
    assert status["command"]["id"] == "cmd_bg"
    history = await manager.list_commands("sbx_test")
    assert history[0]["id"] == "cmd_bg"
    logs = await manager.command_logs("sbx_test", "cmd_bg")
    assert logs["text"] == "server ready"
    killed = await manager.kill_command("sbx_test", "cmd_bg", signal=15)
    assert killed["signal"] == 15
    assert provider.kills[-1] == ("sbx_test", "cmd_bg", 15)

    with pytest.raises(ValueError):
        await manager.kill_command("sbx_test", "cmd_bg", signal=1)
    with pytest.raises(ValueError):
        await manager.start("sbx_test", "sleep", ["1"], timeout_ms=3_600_001)


@pytest.mark.asyncio
async def test_package_install_uses_structured_arguments() -> None:
    provider = FakeProvider()
    manager = SandboxManager(provider)
    await manager.install_packages("sbx_test", ["git", "jq"], manager="apt")
    _, command, args, opts = provider.commands[-1]
    assert command == "apt-get"
    assert args == ["install", "-y", "--no-install-recommends", "git", "jq"]
    assert opts["sudo"] is True

    with pytest.raises(ValueError):
        await manager.install_packages("sbx_test", ["--evil"], manager="apt")


@pytest.mark.asyncio
async def test_git_clone_rejects_credentials_and_non_https() -> None:
    provider = FakeProvider()
    manager = SandboxManager(provider)
    await manager.git_clone("sbx_test", "https://github.com/example/project.git")
    assert provider.commands[-1][1] == "git"

    with pytest.raises(ValueError):
        await manager.git_clone("sbx_test", "git@github.com:example/project.git")
    with pytest.raises(ValueError):
        await manager.git_clone("sbx_test", "https://user:pass@example.com/repo.git")


@pytest.mark.asyncio
async def test_file_round_trip_binary_and_artifact_hashing() -> None:
    provider = FakeProvider()
    manager = SandboxManager(provider)
    await manager.write_file("sbx_test", "notes/a.txt", "hello")
    result = await manager.read_file("sbx_test", "notes/a.txt")
    assert result["content"] == "hello"
    assert result["encoding"] == "utf-8"

    provider.files[("sbx_test", "raw.bin")] = b"\xff\x00"
    binary = await manager.read_file("sbx_test", "raw.bin")
    assert binary["encoding"] == "base64"

    artifact = await manager.artifact("sbx_test", "notes/a.txt")
    assert artifact["media_type"] == "text/plain"
    assert artifact["sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert artifact["bytes"] == 5
    assert artifact["encoding"] == "base64"


@pytest.mark.asyncio
async def test_start_service_requires_pre_published_port() -> None:
    provider = FakeProvider()
    manager = SandboxManager(provider)
    service = await manager.start_service(
        "workbench",
        "python",
        ["-m", "http.server", "3000", "--bind", "0.0.0.0"],
        port=3000,
    )
    assert service["url"] == "https://workbench-3000.example"
    assert service["process"]["command_id"] == "cmd_bg"

    with pytest.raises(ValueError, match="not published"):
        await manager.start_service(
            "workbench", "python", ["-m", "http.server", "8080"], port=8080
        )


@pytest.mark.asyncio
async def test_lifecycle_stop_delete_and_fork() -> None:
    provider = FakeProvider()
    manager = SandboxManager(provider)
    stopped = await manager.stop("sbx_test")
    assert stopped["session"]["status"] == "stopped"
    deleted = await manager.delete("workbench")
    assert deleted["deleted"] is True

    forked = await manager.fork(
        "workbench",
        "workbench-copy",
        ports=[3000],
        vcpus=2,
        memory_mb=2048,
    )
    assert forked["session_id"] == "sbx_fork"
    assert provider.forked[-1][0:2] == ("workbench", "workbench-copy")

    with pytest.raises(ValueError):
        await manager.fork("workbench", "bad copy")
    with pytest.raises(ValueError):
        await manager.fork("workbench", "copy", vcpus=99)


def test_default_network_policy_blocks_private_and_metadata_ranges() -> None:
    policy = public_network_policy()
    assert policy["mode"] == "allow-all"
    assert "127.0.0.0/8" in PUBLIC_NETWORK_DENY_CIDRS
    assert "169.254.0.0/16" in PUBLIC_NETWORK_DENY_CIDRS
    assert "10.0.0.0/8" in policy["deniedCIDRs"]
