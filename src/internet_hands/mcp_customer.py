from __future__ import annotations

from typing import Any

from .mcp_gateway import MCPGatewayASGI
from .mcp_server import _transport_security, sandbox_mcp


def customer_streamable_http_app() -> Any:
    """Return the production customer MCP surface with dynamic auth and metering."""
    raw = sandbox_mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=_transport_security(),
    )
    return MCPGatewayASGI(raw)
