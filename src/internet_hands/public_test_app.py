from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .public_test_mcp import public_test_mcp, streamable_http_app


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with public_test_mcp.session_manager.run():
        yield


app = FastAPI(
    title="Internet Hands Public MCP Test",
    version="0.5.0-test",
    description=(
        "No-auth public test endpoint exposing only discovery, schema inspection, routing, "
        "and gaming profile planning. Execution and sandbox tools are intentionally absent."
    ),
    lifespan=lifespan,
)
app.mount("/mcp", streamable_http_app())


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {
        "status": "ok",
        "server": "Internet Hands Public MCP Test",
        "version": "0.5.0-test",
        "auth": False,
        "mcp": "/mcp/",
        "execution": False,
    }
