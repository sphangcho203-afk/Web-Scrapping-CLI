from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query

from .crawler import crawl
from .fetcher import extract_links, fetch_url, health_check, inspect_api, inspect_download
from .monitor import monitor_once

app = FastAPI(
    title="Internet Hands",
    version="0.1.0",
    description="Raw internet intelligence API for authorized public-web collection.",
)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("INTERNET_HANDS_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="invalid API key")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/fetch", dependencies=[Depends(require_api_key)])
async def api_fetch(url: str = Query(...), include_body: bool = False):
    return await fetch_url(url, include_body=include_body)


@app.get("/v1/links", dependencies=[Depends(require_api_key)])
async def api_links(url: str = Query(...)):
    result = await fetch_url(url, include_body=True)
    return extract_links(result)


@app.get("/v1/api", dependencies=[Depends(require_api_key)])
async def api_inspect(url: str = Query(...)):
    return await inspect_api(url)


@app.get("/v1/health", dependencies=[Depends(require_api_key)])
async def api_health(url: str = Query(...)):
    return await health_check(url)


@app.get("/v1/crawl", dependencies=[Depends(require_api_key)])
async def api_crawl(url: str = Query(...), max_pages: int = Query(25, ge=1, le=100)):
    return await crawl(url, max_pages=max_pages)


@app.get("/v1/download-info", dependencies=[Depends(require_api_key)])
async def api_download_info(url: str = Query(...)):
    return await inspect_download(url)


@app.get("/v1/monitor", dependencies=[Depends(require_api_key)])
async def api_monitor(url: str = Query(...), state: str = Query(".internet-hands/state.json")):
    return await monitor_once(url, Path(state))
