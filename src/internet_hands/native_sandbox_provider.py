from __future__ import annotations

import os
import uuid
from typing import Any

from .sandbox_manager import SandboxManager
from .tool_mesh import ToolDescriptor
from .vercel_sandbox import VercelSandboxProvider


class NativeSandboxToolProvider:
    """First-party Vercel Sandbox fallback for isolated code execution."""

    name = "nativesandbox"

    def __init__(self, manager: SandboxManager | None = None) -> None:
        self._manager = manager

    def _configured(self) -> bool:
        if self._manager is not None:
            return True
        token = (
            os.getenv("VERCEL_OIDC_TOKEN")
            or os.getenv("INTERNET_HANDS_VERCEL_TOKEN")
            or os.getenv("VERCEL_TOKEN")
        )
        project_id = (
            os.getenv("INTERNET_HANDS_SANDBOX_PROJECT_ID")
            or os.getenv("VERCEL_PROJECT_ID")
        )
        return bool(token and project_id)

    def _manager_or_raise(self) -> SandboxManager:
        if self._manager is not None:
            return self._manager
        return SandboxManager(VercelSandboxProvider())

    async def status(self) -> dict[str, Any]:
        configured = self._configured()
        return {
            "configured": configured,
            "searchable": True,
            "executable": configured,
            "kind": "first-party-sandbox",
            "tool_count": 1,
        }

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        descriptor = await self.describe("exec")
        haystack = " ".join(
            [descriptor.tool_id, descriptor.name, descriptor.description, *descriptor.tags]
        ).casefold()
        words = [word for word in query.casefold().split() if word]
        if words and not any(word in haystack for word in words):
            return []
        return [descriptor][: max(1, min(limit, 10))]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        if tool_id != "exec":
            raise ValueError(f"unknown nativesandbox tool: {tool_id}")
        return ToolDescriptor(
            ref="nativesandbox:exec",
            provider=self.name,
            tool_id="exec",
            name="Native isolated code execution",
            description=(
                "Execute a shell command in a first-party Vercel Sandbox. "
                "Foreground sandboxes are deleted after completion; background sandboxes are returned."
            ),
            input_schema={
                "type": "object",
                "required": ["command"],
                "properties": {
                    "command": {"type": "string", "minLength": 1, "maxLength": 50000},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 600},
                    "background": {"type": "boolean"},
                    "restart": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            output_schema={},
            tags=["code", "shell", "sandbox", "fallback", "native"],
            requires_auth=True,
            side_effecting=True,
            metadata={"configured": self._configured(), "fallback": True},
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
        del account, wait_seconds, options
        await self.describe(tool_id)
        command = str(arguments.get("command") or "").strip()
        if not command:
            raise ValueError("command is required")
        if bool(arguments.get("restart", False)):
            raise ValueError("restart is unsupported by the native sandbox fallback")

        timeout = max(
            1,
            min(int(arguments.get("timeout_seconds", timeout_seconds)), 600),
        )
        background = bool(arguments.get("background", False))
        manager = self._manager_or_raise()
        sandbox_name = f"ih-code-{uuid.uuid4().hex[:12]}"
        created = await manager.create(
            sandbox_name,
            timeout=f"{max(5, min((timeout // 60) + 2, 15))}m",
            persistent=background,
        )
        session_id = str(created["session_id"])

        if background:
            result = await manager.start(
                session_id,
                "/bin/sh",
                ["-lc", command],
                timeout_ms=timeout * 1000,
            )
            return {
                "status": "running",
                "job_id": result.get("command_id"),
                "data": {
                    "sandbox_name": sandbox_name,
                    "session_id": session_id,
                    "command": result,
                    "cleanup_required": True,
                },
                "metadata": {
                    "provider": "vercel-sandbox",
                    "sandbox_name": sandbox_name,
                    "cleanup_required": True,
                },
            }

        try:
            result = await manager.shell(
                session_id,
                command,
                timeout_ms=timeout * 1000,
            )
            return {
                "status": "completed" if result.get("exit_code") in (0, None) else "failed",
                "data": result,
                "error": (
                    None
                    if result.get("exit_code") in (0, None)
                    else f"command exited with code {result.get('exit_code')}"
                ),
                "metadata": {"provider": "vercel-sandbox", "ephemeral": True},
            }
        finally:
            try:
                await manager.delete(sandbox_name)
            except Exception:
                # Command outcome is more important than cleanup telemetry. The sandbox
                # timeout remains a hard upper bound if deletion is temporarily unavailable.
                pass

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        del job_id, wait_seconds
        raise ValueError(
            "background native sandbox jobs are inspected through first-party sandbox tools"
        )

    async def result_page(
        self, result_id: str, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        del result_id, offset, limit
        raise ValueError("native sandbox execution returns bounded inline command output")
