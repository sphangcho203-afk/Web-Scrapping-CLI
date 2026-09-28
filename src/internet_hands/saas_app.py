# ruff: noqa: I001
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import account_mcp as _account_mcp  # noqa: F401
from .control_api import router as control_router
from .connected_apps_api import router as connected_apps_router
from .control_hardening import router as hardening_router
from .control_migration import run_requested_control_plane_migration
from .fleet_api import app as fleet_app
from .game_api import router as game_router
from .intelligence_api import router as intelligence_router
from .mcp_customer import customer_streamable_http_app
from .mcp_server import sandbox_mcp
from .monitor_executor import router as monitor_executor_router
from .monitor_lifecycle import router as monitor_lifecycle_router
from .oauth_compat import router as oauth_compat_router
from .playground_api import router as playground_router
from .public_data_api import router as public_data_router
from .repository_api import router as repository_router
from .security_api import router as security_router
from .security_hardening import router as security_hardening_router
from .site import router as site_router
from .system_health import router as system_health_router
from .usage_api import router as usage_router


logger = logging.getLogger(__name__)


class MCPPathAlias:
    """Serve the advertised /mcp URL without a 307 before client auth."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/mcp":
            scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    migration = await asyncio.to_thread(run_requested_control_plane_migration)
    if migration:
        logger.info("startup control-plane migration result", extra={"migration": migration})
    async with sandbox_mcp.session_manager.run():
        yield


app = FastAPI(
    title="OpenCrawl",
    version="0.7.0",
    description=(
        "OpenCrawl SaaS control plane, permanent MCP gateway, transactional email, "
        "email verification, TOTP 2FA, billing, usage metering, monitors, and capability fabric."
    ),
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(MCPPathAlias)

# Security and hardened compatibility overrides are registered first so they take precedence.
app.include_router(oauth_compat_router)
app.include_router(security_hardening_router)
app.include_router(security_router)
app.include_router(hardening_router)
app.include_router(monitor_executor_router)
app.include_router(monitor_lifecycle_router)
app.include_router(system_health_router)
app.include_router(control_router)
app.include_router(connected_apps_router)
app.include_router(usage_router)
app.include_router(playground_router)
app.include_router(repository_router)
app.include_router(public_data_router)
app.include_router(game_router)
app.include_router(intelligence_router)
app.include_router(site_router)
app.mount("/mcp", customer_streamable_http_app())

# Preserve the existing fleet/data-plane routes behind the same origin.
app.mount("/", fleet_app)
