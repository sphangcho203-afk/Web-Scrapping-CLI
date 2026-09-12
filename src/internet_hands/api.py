from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query

from .browser import render_page
from .crawler import crawl
from .endpoints import Capability, endpoint_catalog
from .fetcher import extract_links, fetch_url, health_check, inspect_api, inspect_download
from .intel import (
    bluesky_profile,
    github_user,
    public_username_scan,
    youtube_channel,
    youtube_owner_analytics,
    youtube_video,
)
from .monitor import monitor_once
from .pipeline import index_crawl, index_url, run_due_watches
from .storage import DEFAULT_DB, Store

app = FastAPI(
    title="Internet Hands",
    version="0.3.0",
    description="Public internet intelligence and provenance API for apps and agents.",
)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
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


def db_path() -> Path:
    return Path(os.getenv("INTERNET_HANDS_DB", str(DEFAULT_DB)))


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": "0.3.0"}


@app.get("/v1/endpoints", dependencies=[Depends(require_api_key)])
def api_endpoints(
    provider: str | None = None,
    capability: Capability | None = None,
    ready_only: bool = False,
):
    return [
        {
            "provider": item.provider,
            "name": item.name,
            "capability": item.capability.value,
            "method": item.method,
            "url": item.url,
            "auth": item.auth.value,
            "env": list(item.env),
            "ready": item.ready,
            "public_data": item.public_data,
            "notes": item.notes,
        }
        for item in endpoint_catalog(
            provider=provider,
            capability=capability,
            ready_only=ready_only,
        )
    ]


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


@app.post("/v1/index", dependencies=[Depends(require_api_key)])
async def api_index(url: str = Query(...)):
    return await index_url(url, db_path=db_path())


@app.post("/v1/index-crawl", dependencies=[Depends(require_api_key)])
async def api_index_crawl(url: str = Query(...), max_pages: int = Query(25, ge=1, le=100)):
    return await index_crawl(url, db_path=db_path(), max_pages=max_pages)


@app.get("/v1/search", dependencies=[Depends(require_api_key)])
def api_search(q: str = Query(...), limit: int = Query(20, ge=1, le=200)):
    return Store(db_path()).search(q, limit=limit)


@app.post("/v1/watch", dependencies=[Depends(require_api_key)])
def api_watch_add(url: str = Query(...), every: int = Query(3600, ge=60)):
    return Store(db_path()).add_watch(url, every)


@app.get("/v1/watch", dependencies=[Depends(require_api_key)])
def api_watch_list():
    return Store(db_path()).list_watches()


@app.post("/v1/watch/run", dependencies=[Depends(require_api_key)])
async def api_watch_run(limit: int = Query(100, ge=1, le=1000)):
    return await run_due_watches(db_path=db_path(), limit=limit)


@app.get("/v1/browser", dependencies=[Depends(require_api_key)])
async def api_browser(url: str = Query(...), include_html: bool = False):
    result = await render_page(url)
    if not include_html:
        result = result.model_copy(update={"html": ""})
    return result


@app.get("/v1/download-info", dependencies=[Depends(require_api_key)])
async def api_download_info(url: str = Query(...)):
    return await inspect_download(url)


@app.get("/v1/monitor", dependencies=[Depends(require_api_key)])
async def api_monitor(url: str = Query(...), state: str = Query(".internet-hands/state.json")):
    return await monitor_once(url, Path(state))


@app.get("/v1/intel/youtube/video", dependencies=[Depends(require_api_key)])
async def api_intel_youtube_video(target: str = Query(...)):
    return await youtube_video(target)


@app.get("/v1/intel/youtube/channel", dependencies=[Depends(require_api_key)])
async def api_intel_youtube_channel(target: str = Query(...)):
    return await youtube_channel(target)


@app.get("/v1/intel/youtube/owner-analytics", dependencies=[Depends(require_api_key)])
async def api_intel_youtube_owner_analytics(
    start: date = Query(...),
    end: date = Query(...),
    video: str | None = None,
    currency: str = "USD",
):
    return await youtube_owner_analytics(
        start,
        end,
        video_id=video,
        currency=currency,
    )


@app.get("/v1/intel/github/user", dependencies=[Depends(require_api_key)])
async def api_intel_github_user(username: str = Query(...)):
    return await github_user(username)


@app.get("/v1/intel/bluesky/profile", dependencies=[Depends(require_api_key)])
async def api_intel_bluesky_profile(actor: str = Query(...)):
    return await bluesky_profile(actor)


@app.get("/v1/intel/username", dependencies=[Depends(require_api_key)])
async def api_intel_username(username: str = Query(...)):
    return await public_username_scan(username)
