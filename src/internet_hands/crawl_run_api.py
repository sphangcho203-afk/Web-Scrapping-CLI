from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .control_api import store
from .control_store import ControlError
from .crawl_run_worker import dispatch_run
from .crawl_runs import RunStore
from .datasets_api import _error, _owner
from .monitor_executor import _scheduler_authorized
from .playground_api import _SAFE_EXCLUDES, _patterns, _playground_identity
from .policy import PolicyError, ResolutionUnavailable, validate_public_http_url


def _response(data, status_code=200):
    return JSONResponse(jsonable_encoder(data), status_code=status_code, headers={"Cache-Control": "no-store"})


router = APIRouter()
runs = RunStore(store)


def crawl_arguments(body: dict) -> dict:
    allowed = {"api_key_id", "operation", "url", "max_pages", "max_depth", "concurrency", "max_seconds",
               "include_paths", "exclude_paths", "include_subdomains", "preserve_query", "include_content",
               "max_content_bytes_per_page", "max_content_bytes"}
    if set(body) - allowed or body.get("operation", "crawl") != "crawl":
        raise HTTPException(422, detail="Background runs currently support URL crawls and their documented options.")
    url = body.get("url")
    if not isinstance(url, str) or not url.strip() or len(url) > 4096:
        raise HTTPException(422, detail="A public URL of at most 4096 characters is required.")
    args = {"url": url.strip()}
    for name, default, low, high in (("max_pages", 12, 1, 50), ("max_depth", 2, 0, 4),
        ("concurrency", 4, 1, 6), ("max_seconds", 30, 5, 45),
        ("max_content_bytes_per_page", 50000, 1, 50000), ("max_content_bytes", 500000, 1, 500000)):
        value = body.get(name, default)
        if type(value) is not int or not low <= value <= high:
            raise HTTPException(422, detail=f"{name} must be an integer between {low} and {high}.")
        args[name] = value
    for name, default in (("include_subdomains", False), ("preserve_query", False), ("include_content", True)):
        value = body.get(name, default)
        if not isinstance(value, bool):
            raise HTTPException(422, detail=f"{name} must be a boolean.")
        args[name] = value
    args["include_paths"] = sorted(set(_patterns(body.get("include_paths"), "include_paths")))
    args["exclude_paths"] = sorted({*_SAFE_EXCLUDES, *_patterns(body.get("exclude_paths"), "exclude_paths")})
    return args


@router.post("/api/crawl-runs", status_code=202)
async def create_run(request: Request):
    raw = await request.body()
    if len(raw) > 65536:
        raise HTTPException(413, detail="Crawl request exceeds 64 KB.")
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, detail="Expected a JSON object.") from exc
    if not isinstance(body, dict):
        raise HTTPException(422, detail="Expected a JSON object.")
    identity = await run_in_threadpool(_playground_identity, request, body)
    args = crawl_arguments(body)
    try:
        await asyncio.to_thread(validate_public_http_url, args["url"])
        run = await run_in_threadpool(runs.create, identity, request.headers.get("idempotency-key", ""), args)
        return _response({"run": run}, status_code=202)
    except ResolutionUnavailable as exc:
        raise HTTPException(503, detail={"code": "resolver_busy", "message": "URL resolution is unavailable."}) from exc
    except PolicyError as exc:
        raise HTTPException(422, detail={"code": "target_blocked", "message": str(exc)}) from exc
    except ControlError as exc:
        raise _error(exc) from exc


@router.get("/api/crawl-runs")
def list_runs(request: Request, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0, le=100000)):
    return _response(runs.list(_owner(request), limit, offset))


@router.get("/api/crawl-runs/{run_id}")
def get_run(request: Request, run_id: str):
    owner = _owner(request)
    try:
        return _response({"run": runs.get(owner, run_id)})
    except ControlError as exc:
        raise _error(exc) from exc


@router.post("/api/crawl-runs/{run_id}/cancel")
def cancel_run(request: Request, run_id: str):
    owner = _owner(request, write=True)
    try:
        return _response({"run": runs.cancel(owner, run_id)})
    except ControlError as exc:
        raise _error(exc) from exc


@router.get("/api/internal/crawl-runs/tick")
async def run_tick(request: Request):
    await _scheduler_authorized(request.headers.get("authorization"))
    return await dispatch_run(runs)
