from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import account_mcp as _account_mcp  # noqa: F401
from .control_api import router as control_router
from .fleet_api import app as fleet_app
from .mcp_customer import customer_streamable_http_app
from .mcp_server import sandbox_mcp
from .site import router as site_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with sandbox_mcp.session_manager.run():
        yield


app = FastAPI(
    title="Internet Hands",
    version="0.6.0",
    description=(
        "Internet Hands SaaS control plane, permanent MCP gateway, customer console, "
        "billing, usage metering, monitors, and capability fabric."
    ),
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

# Product/control routes take precedence over the legacy fleet app.
app.include_router(control_router)
app.include_router(site_router)
app.mount("/mcp", customer_streamable_http_app())

# Preserve the existing v0.5 fleet/data-plane routes behind the same origin.
app.mount("/", fleet_app)
