from __future__ import annotations

import base64
import re
from dataclasses import asdict
from typing import Any
from urllib.parse import urlparse

from .sandbox_models import CommandResult, SandboxSpec
from .sandbox_policy import (
    SandboxLimits,
    validate_name,
    validate_packages,
    validate_ports,
    validate_resources,
    validate_timeout_ms,
)
from .sandbox_provider import SandboxProvider

_GIT_SHAISH = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")


class SandboxManager:
    def __init__(
        self, provider: SandboxProvider, *, limits: SandboxLimits | None = None
    ) -> None:
        self.provider = provider
        self.limits = limits or SandboxLimits()

    async def create(
        self,
        name: str,
        *,
        timeout: str = "30m",
        vcpus: int = 2,
        memory_mb: int = 4096,
        ports: list[int] | None = None,
        image: str | None = None,
        persistent: bool = True,
    ) -> dict[str, Any]:
        name = validate_name(name)
        validate_resources(vcpus, memory_mb, self.limits)
        checked_ports = validate_ports(ports or [], self.limits)
        ref = await self.provider.create(
            SandboxSpec(
                name=name,
                timeout=timeout,
                vcpus=vcpus,
                memory_mb=memory_mb,
                ports=checked_ports,
                image=image,
                persistent=persistent,
            )
        )
        return asdict(ref)

    async def get(self, name: str, *, resume: bool = True) -> dict[str, Any]:
        return asdict(await self.provider.get(validate_name(name), resume=resume))

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
    ) -> dict[str, Any]:
        if not command.strip() or len(command) > 500:
            raise ValueError("command must contain 1-500 characters")
        timeout_ms = validate_timeout_ms(timeout_ms, self.limits)
        result = await self.provider.exec(
            session_id,
            command.strip(),
            args or [],
            cwd=cwd,
            env=env,
            sudo=sudo,
            timeout_ms=timeout_ms,
        )
        return self._command_dict(result)

    async def shell(
        self,
        session_id: str,
        script: str,
        *,
        cwd: str | None = None,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        if not script.strip() or len(script) > 50_000:
            raise ValueError("script must contain 1-50000 characters")
        return await self.exec(
            session_id,
            "/bin/sh",
            ["-lc", script],
            cwd=cwd,
            timeout_ms=timeout_ms,
        )

    async def install_packages(
        self,
        session_id: str,
        packages: list[str],
        *,
        manager: str = "apt",
        cwd: str | None = None,
        timeout_ms: int = 120_000,
    ) -> dict[str, Any]:
        packages = validate_packages(packages)
        if manager == "apt":
            return await self.exec(
                session_id,
                "apt-get",
                ["install", "-y", "--no-install-recommends", *packages],
                cwd=cwd,
                sudo=True,
                timeout_ms=timeout_ms,
            )
        if manager == "pip":
            return await self.exec(
                session_id,
                "python",
                ["-m", "pip", "install", *packages],
                cwd=cwd,
                timeout_ms=timeout_ms,
            )
        if manager == "npm":
            return await self.exec(
                session_id,
                "npm",
                ["install", *packages],
                cwd=cwd,
                timeout_ms=timeout_ms,
            )
        raise ValueError("manager must be one of: apt, pip, npm")

    async def git_clone(
        self,
        session_id: str,
        url: str,
        *,
        destination: str | None = None,
        revision: str | None = None,
        depth: int = 1,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("git URL must use public HTTPS")
        if parsed.username or parsed.password:
            raise ValueError("credentials must not be embedded in git URLs")
        if not 1 <= depth <= 100:
            raise ValueError("depth must be between 1 and 100")
        args = ["clone", "--depth", str(depth)]
        if revision:
            if not _GIT_SHAISH.fullmatch(revision) or revision.startswith("-"):
                raise ValueError("invalid git revision")
            args += ["--branch", revision]
        args.append(url)
        if destination:
            if destination.startswith("-") or ".." in destination.split("/"):
                raise ValueError("invalid clone destination")
            args.append(destination)
        return await self.exec(
            session_id, "git", args, cwd=cwd, timeout_ms=120_000
        )

    async def read_file(
        self,
        session_id: str,
        path: str,
        *,
        cwd: str | None = None,
        max_bytes: int = 1_000_000,
    ) -> dict[str, Any]:
        if not 1 <= max_bytes <= self.limits.max_output_bytes:
            raise ValueError("max_bytes exceeds sandbox output policy")
        data = await self.provider.read_file(session_id, path, cwd=cwd)
        truncated = len(data) > max_bytes
        data = data[:max_bytes]
        try:
            text = data.decode("utf-8")
            return {
                "path": path,
                "encoding": "utf-8",
                "content": text,
                "truncated": truncated,
            }
        except UnicodeDecodeError:
            return {
                "path": path,
                "encoding": "base64",
                "content": base64.b64encode(data).decode(),
                "truncated": truncated,
            }

    async def write_file(
        self,
        session_id: str,
        path: str,
        content: str,
        *,
        cwd: str | None = None,
        encoding: str = "utf-8",
    ) -> dict[str, Any]:
        if encoding == "utf-8":
            data = content.encode()
        elif encoding == "base64":
            data = base64.b64decode(content, validate=True)
        else:
            raise ValueError("encoding must be utf-8 or base64")
        if len(data) > self.limits.max_output_bytes:
            raise ValueError("file exceeds sandbox write limit")
        await self.provider.write_file(session_id, path, data, cwd=cwd)
        return {"path": path, "bytes": len(data), "written": True}

    async def mkdir(
        self, session_id: str, path: str, *, cwd: str | None = None
    ) -> dict[str, Any]:
        if not path.strip() or path.startswith("-"):
            raise ValueError("invalid directory path")
        return await self.exec(session_id, "mkdir", ["-p", "--", path], cwd=cwd)

    async def browser_screenshot(
        self,
        session_id: str,
        url: str,
        *,
        output_path: str = "artifacts/page.png",
        cwd: str | None = None,
        timeout_ms: int = 120_000,
    ) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("browser URL must be http(s)")
        install = await self.exec(
            session_id,
            "npx",
            ["--yes", "playwright", "install", "chromium"],
            cwd=cwd,
            timeout_ms=timeout_ms,
        )
        if install.get("exit_code") not in (0, None):
            return {"stage": "install", "result": install}
        shot = await self.exec(
            session_id,
            "npx",
            ["--yes", "playwright", "screenshot", "--full-page", url, output_path],
            cwd=cwd,
            timeout_ms=timeout_ms,
        )
        return {"stage": "screenshot", "path": output_path, "result": shot}

    async def snapshot(self, session_id: str) -> dict[str, object]:
        return await self.provider.snapshot(session_id)

    @staticmethod
    def _command_dict(result: CommandResult) -> dict[str, Any]:
        return {
            "session_id": result.session_id,
            "command_id": result.command_id,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "events": result.events,
        }
