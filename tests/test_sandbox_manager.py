from __future__ import annotations

import pytest

from internet_hands.sandbox_manager import SandboxManager
from internet_hands.sandbox_models import CommandResult, SandboxRef, SandboxSpec
from internet_hands.sandbox_policy import PUBLIC_NETWORK_DENY_CIDRS, public_network_policy


class FakeProvider:
    def __init__(self) -> None:
        self.created: SandboxSpec | None = None
        self.commands: list[tuple[str, str, list[str], dict[str, object]]] = []
        self.files: dict[tuple[str, str], bytes] = {}

    async def create(self, spec: SandboxSpec) -> SandboxRef:
        self.created = spec
        return SandboxRef(spec.name, "sbx_test", "running", routes=[{"port": 3000}])

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
        self.commands.append(
            (
                session_id,
                command,
                args or [],
                {"cwd": cwd, "env": env, "sudo": sudo, "timeout_ms": timeout_ms},
            )
        )
        return CommandResult(session_id, "cmd_test", 0, "ok", "")

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
async def test_file_round_trip_and_binary_encoding() -> None:
    provider = FakeProvider()
    manager = SandboxManager(provider)
    await manager.write_file("sbx_test", "notes/a.txt", "hello")
    result = await manager.read_file("sbx_test", "notes/a.txt")
    assert result["content"] == "hello"
    assert result["encoding"] == "utf-8"

    provider.files[("sbx_test", "raw.bin")] = b"\xff\x00"
    binary = await manager.read_file("sbx_test", "raw.bin")
    assert binary["encoding"] == "base64"


def test_default_network_policy_blocks_private_and_metadata_ranges() -> None:
    policy = public_network_policy()
    assert policy["mode"] == "allow-all"
    assert "127.0.0.0/8" in PUBLIC_NETWORK_DENY_CIDRS
    assert "169.254.0.0/16" in PUBLIC_NETWORK_DENY_CIDRS
    assert "10.0.0.0/8" in policy["deniedCIDRs"]
