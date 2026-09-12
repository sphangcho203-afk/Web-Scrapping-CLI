from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SandboxSpec:
    name: str
    timeout: str = "30m"
    vcpus: int = 2
    memory_mb: int = 4096
    image: str | None = None
    ports: list[int] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    persistent: bool = True


@dataclass(slots=True)
class SandboxRef:
    name: str
    session_id: str
    status: str
    provider: str = "vercel"
    routes: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CommandResult:
    session_id: str
    command_id: str | None
    exit_code: int | None
    stdout: str
    stderr: str
    events: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
