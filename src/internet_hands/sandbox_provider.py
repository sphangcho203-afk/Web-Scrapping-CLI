from __future__ import annotations

from typing import Any, Protocol

from .sandbox_models import CommandResult, SandboxRef, SandboxSpec


class SandboxProvider(Protocol):
    async def create(self, spec: SandboxSpec) -> SandboxRef: ...

    async def get(self, name: str, *, resume: bool = True) -> SandboxRef: ...

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
    ) -> CommandResult: ...

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
    ) -> CommandResult: ...

    async def command(
        self,
        session_id: str,
        command_id: str,
        *,
        wait: bool = False,
    ) -> dict[str, Any]: ...

    async def list_commands(self, session_id: str) -> list[dict[str, Any]]: ...

    async def command_logs(
        self,
        session_id: str,
        command_id: str,
        *,
        max_bytes: int = 1_000_000,
    ) -> dict[str, Any]: ...

    async def kill_command(
        self,
        session_id: str,
        command_id: str,
        *,
        signal: int = 15,
    ) -> dict[str, Any]: ...

    async def read_file(self, session_id: str, path: str, *, cwd: str | None = None) -> bytes: ...

    async def write_file(
        self, session_id: str, path: str, content: bytes, *, cwd: str | None = None
    ) -> None: ...

    async def snapshot(self, session_id: str) -> dict[str, object]: ...

    async def stop(self, session_id: str) -> dict[str, Any]: ...

    async def delete(self, name: str) -> dict[str, Any]: ...

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
    ) -> SandboxRef: ...
