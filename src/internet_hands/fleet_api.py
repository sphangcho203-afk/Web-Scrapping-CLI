from __future__ import annotations

import asyncio
import dataclasses
import json
import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from .hunt import HuntScope
from .postgres_frontier import PostgresFrontier
from .postgres_store import PostgresCaptureStore
from .telemetry import DEFAULT_TELEMETRY_DB, PostgresTelemetry, SqliteTelemetry

app = FastAPI(
    title="Internet Hands Fleet",
    version="0.3.0",
    description="Distributed crawl frontier, shared content index, and telemetry control plane.",
)


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = os.getenv("INTERNET_HANDS_API_KEY")
    allow_unauthenticated = os.getenv("INTERNET_HANDS_ALLOW_UNAUTHENTICATED") == "1"
    if not expected:
        if allow_unauthenticated:
            return
        raise HTTPException(
            status_code=503,
            detail=(
                "API key is not configured. Set INTERNET_HANDS_API_KEY or explicitly "
                "set INTERNET_HANDS_ALLOW_UNAUTHENTICATED=1 for trusted local use."
            ),
        )
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="invalid API key")


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise HTTPException(status_code=503, detail=f"{name} is not configured")
    return value


def _frontier() -> PostgresFrontier:
    return PostgresFrontier(_required_env("INTERNET_HANDS_POSTGRES_DSN"))


def _content_store() -> PostgresCaptureStore:
    return PostgresCaptureStore(_required_env("INTERNET_HANDS_CONTENT_POSTGRES_DSN"))


def _telemetry():
    postgres_dsn = os.getenv("INTERNET_HANDS_TELEMETRY_POSTGRES_DSN")
    if postgres_dsn:
        return PostgresTelemetry(postgres_dsn)
    path = Path(os.getenv("INTERNET_HANDS_TELEMETRY_DB", str(DEFAULT_TELEMETRY_DB)))
    return SqliteTelemetry(path)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": "0.3.0", "plane": "fleet"}


@app.get("/v1/frontier/stats", dependencies=[Depends(require_api_key)])
def frontier_stats():
    return _frontier().stats()


@app.post("/v1/frontier/seed", dependencies=[Depends(require_api_key)])
def frontier_seed(
    url: Annotated[str, Query()],
    scope: Annotated[HuntScope, Query()] = HuntScope.ORIGIN,
    priority: Annotated[int, Query(ge=-1000, le=1000)] = 0,
    max_attempts: Annotated[int, Query(ge=1, le=50)] = 4,
):
    added = _frontier().enqueue(
        url,
        root_url=url,
        scope=scope.value,
        priority=priority,
        max_attempts=max_attempts,
    )
    return {"url": url, "added": bool(added)}


@app.get("/v1/content/stats", dependencies=[Depends(require_api_key)])
def content_stats():
    return _content_store().stats()


@app.get("/v1/content/recent", dependencies=[Depends(require_api_key)])
def content_recent(limit: Annotated[int, Query(ge=1, le=1000)] = 50):
    return _content_store().recent_captures(limit=limit)


@app.get("/v1/search", dependencies=[Depends(require_api_key)])
def search(
    q: Annotated[str, Query()],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
):
    return _content_store().search(q, limit=limit)


@app.get("/v1/events", dependencies=[Depends(require_api_key)])
def events(
    after_id: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
):
    return [dataclasses.asdict(item) for item in _telemetry().list_events(after_id=after_id, limit=limit)]


@app.get("/v1/events/stream", dependencies=[Depends(require_api_key)])
def event_stream(
    after_id: Annotated[int, Query(ge=0)] = 0,
    poll_seconds: Annotated[float, Query(ge=0.1, le=30.0)] = 1.0,
):
    telemetry = _telemetry()

    async def stream():
        cursor = after_id
        idle_ticks = 0
        while True:
            batch = telemetry.list_events(after_id=cursor, limit=250)
            if batch:
                idle_ticks = 0
                for item in batch:
                    cursor = item.id
                    payload = json.dumps(dataclasses.asdict(item), default=str, separators=(",", ":"))
                    yield f"id: {item.id}\nevent: {item.event_type}\ndata: {payload}\n\n"
            else:
                idle_ticks += 1
                if idle_ticks >= max(1, int(15 / poll_seconds)):
                    idle_ticks = 0
                    yield ": keep-alive\n\n"
                await asyncio.sleep(poll_seconds)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def run() -> None:
    import uvicorn

    host = os.getenv("INTERNET_HANDS_FLEET_API_HOST", "0.0.0.0")
    port = int(os.getenv("INTERNET_HANDS_FLEET_API_PORT", "8788"))
    uvicorn.run("internet_hands.fleet_api:app", host=host, port=port)