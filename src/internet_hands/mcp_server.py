from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from .sandbox_manager import SandboxManager
from .vercel_sandbox import VercelSandboxProvider

sandbox_mcp = MCPServer(
    "Internet Hands",
    instructions=(
        "Isolated public-internet cloud computer tools. Create a sandbox before using a session. "
        "Sandboxes deny private, loopback, link-local, and metadata networks by default."
    ),
)


@lru_cache(maxsize=1)
def get_sandbox_manager() -> SandboxManager:
    return SandboxManager(VercelSandboxProvider())


def _transport_security() -> TransportSecuritySettings:
    hosts = {"127.0.0.1", "localhost"}
    for env_name in (
        "VERCEL_URL",
        "VERCEL_PROJECT_PRODUCTION_URL",
        "INTERNET_HANDS_PUBLIC_HOST",
    ):
        value = os.getenv(env_name, "").strip()
        if value:
            value = value.removeprefix("https://").removeprefix("http://").rstrip("/")
            hosts.add(value)
    allowed_hosts: list[str] = []
    allowed_origins: list[str] = []
    for host in sorted(hosts):
        allowed_hosts.extend([host, f"{host}:*"])
        if host in {"127.0.0.1", "localhost"}:
            allowed_origins.extend([f"http://{host}", f"http://{host}:*"])
        else:
            allowed_origins.append(f"https://{host}")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


class APIKeyASGI:
    """Protect the mounted MCP endpoint with the Internet Hands API key."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        expected = os.getenv("INTERNET_HANDS_API_KEY")
        if not expected:
            response = JSONResponse({"detail": "API key is not configured"}, status_code=503)
            await response(scope, receive, send)
            return
        supplied = headers.get("x-api-key")
        authorization = headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()
        if supplied != expected:
            response = JSONResponse({"detail": "invalid API key"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def streamable_http_app() -> Any:
    return APIKeyASGI(
        sandbox_mcp.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            json_response=True,
            transport_security=_transport_security(),
        )
    )


@sandbox_mcp.tool()
async def sandbox_create(
    name: str,
    timeout: str = "30m",
    vcpus: int = 2,
    memory_mb: int = 4096,
    ports: list[int] | None = None,
    image: str | None = None,
    persistent: bool = True,
) -> dict[str, Any]:
    """Create an isolated cloud computer with public-internet-only network policy."""
    return await get_sandbox_manager().create(
        name,
        timeout=timeout,
        vcpus=vcpus,
        memory_mb=memory_mb,
        ports=ports,
        image=image,
        persistent=persistent,
    )


@sandbox_mcp.tool()
async def sandbox_get(name: str, resume: bool = True) -> dict[str, Any]:
    """Get or resume a named sandbox and return its active session and public routes."""
    return await get_sandbox_manager().get(name, resume=resume)


@sandbox_mcp.tool()
async def sandbox_exec(
    session_id: str,
    command: str,
    args: list[str] | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    sudo: bool = False,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Execute one program inside the isolated sandbox and return logs/status."""
    return await get_sandbox_manager().exec(
        session_id,
        command,
        args,
        cwd=cwd,
        env=env,
        sudo=sudo,
        timeout_ms=timeout_ms,
    )


@sandbox_mcp.tool()
async def sandbox_shell(
    session_id: str,
    script: str,
    cwd: str | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Run a shell script inside the isolated sandbox."""
    return await get_sandbox_manager().shell(
        session_id, script, cwd=cwd, timeout_ms=timeout_ms
    )


@sandbox_mcp.tool()
async def sandbox_install(
    session_id: str,
    packages: list[str],
    manager: str = "apt",
    cwd: str | None = None,
    timeout_ms: int = 120_000,
) -> dict[str, Any]:
    """Install packages with apt, pip, or npm inside the sandbox."""
    return await get_sandbox_manager().install_packages(
        session_id,
        packages,
        manager=manager,
        cwd=cwd,
        timeout_ms=timeout_ms,
    )


@sandbox_mcp.tool()
async def sandbox_git_clone(
    session_id: str,
    url: str,
    destination: str | None = None,
    revision: str | None = None,
    depth: int = 1,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Clone a public HTTPS Git repository into the sandbox."""
    return await get_sandbox_manager().git_clone(
        session_id,
        url,
        destination=destination,
        revision=revision,
        depth=depth,
        cwd=cwd,
    )


@sandbox_mcp.tool()
async def sandbox_read_file(
    session_id: str,
    path: str,
    cwd: str | None = None,
    max_bytes: int = 1_000_000,
) -> dict[str, Any]:
    """Read a text or binary file; binary data is returned as base64."""
    return await get_sandbox_manager().read_file(
        session_id, path, cwd=cwd, max_bytes=max_bytes
    )


@sandbox_mcp.tool()
async def sandbox_write_file(
    session_id: str,
    path: str,
    content: str,
    cwd: str | None = None,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    """Write UTF-8 or base64 content to a file inside the sandbox."""
    return await get_sandbox_manager().write_file(
        session_id, path, content, cwd=cwd, encoding=encoding
    )


@sandbox_mcp.tool()
async def sandbox_mkdir(
    session_id: str, path: str, cwd: str | None = None
) -> dict[str, Any]:
    """Create a directory tree inside the sandbox."""
    return await get_sandbox_manager().mkdir(session_id, path, cwd=cwd)


@sandbox_mcp.tool()
async def sandbox_browser_screenshot(
    session_id: str,
    url: str,
    output_path: str = "artifacts/page.png",
    cwd: str | None = None,
    timeout_ms: int = 120_000,
) -> dict[str, Any]:
    """Use Chromium via Playwright in the cloud computer and save a screenshot."""
    return await get_sandbox_manager().browser_screenshot(
        session_id,
        url,
        output_path=output_path,
        cwd=cwd,
        timeout_ms=timeout_ms,
    )


@sandbox_mcp.tool()
async def sandbox_snapshot(session_id: str) -> dict[str, object]:
    """Snapshot the filesystem for later restoration; Vercel stops the session."""
    return await get_sandbox_manager().snapshot(session_id)
