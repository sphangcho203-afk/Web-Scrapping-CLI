from __future__ import annotations

from typing import Any

from .mcp_gateway import MCPGatewayASGI
from .mcp_server import _transport_security, sandbox_mcp


class MCPPathMiddleware:
    """Route the advertised /mcp URL internally without a client redirect."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and scope.get("path") == scope.get("root_path", "") + "/mcp":
            scope = {**scope, "path": scope["path"] + "/"}
            if "raw_path" in scope:
                scope["raw_path"] = scope["raw_path"] + b"/"
        await self.app(scope, receive, send)


def customer_streamable_http_app() -> Any:
    """Return the production customer MCP surface with dynamic auth and metering."""
    raw = sandbox_mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=_transport_security(),
    )
    return MCPGatewayASGI(raw)
