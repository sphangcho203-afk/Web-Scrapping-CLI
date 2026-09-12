from __future__ import annotations

from typing import Protocol

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

    async def read_file(self, session_id: str, path: str, *, cwd: str | None = None) -> bytes: ...

    async def write_file(
        self, session_id: str, path: str, content: bytes, *, cwd: str | None = None
    ) -> None: ...

    async def snapshot(self, session_id: str) -> dict[str, object]: ...
