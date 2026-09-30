"""First-class durable Structured Extract workflow."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .capability_run_worker import dispatch_capability_run
from .capability_runs import CapabilityRunStore
from .control_api import store
from .control_store import ControlError
from .datasets_api import _error, _owner
from .monitor_executor import _scheduler_authorized
from .playground_api import _playground_identity, execution_quote
from .policy import PolicyError, ResolutionUnavailable, validate_public_http_url

router = APIRouter()
runs = CapabilityRunStore(store)

_CAPABILITY = "web.extract.structured"
_MAX_BODY_BYTES = 96_000
_MAX_SCHEMA_BYTES = 32_000
_EFFORT_CREDITS = {"low": 5, "medium": 10, "high": 20}


def _response(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        jsonable_encoder(data),
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise HTTPException(
            413,
            detail={
                "code": "input_too_large",
                "message": "Structured extraction requests are limited to 96 KB.",
            },
        )
    try:
        body = json.loads(raw or b"{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(
            400,
            detail={"code": "invalid_json", "message": "Expected a JSON object."},
        ) from exc
    if not isinstance(body, dict):
        raise HTTPException(
            422,
            detail={"code": "invalid_input", "message": "Expected a JSON object."},
        )
    return body


def _bounded_schema(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise HTTPException(
            422,
            detail={"code": "invalid_schema", "message": "schema must be a JSON object."},
        )
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > _MAX_SCHEMA_BYTES:
        raise HTTPException(
            422,
            detail={"code": "invalid_schema", "message": "schema must be at most 32 KB."},
        )

    nodes = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 500 or depth > 12:
            raise HTTPException(
                422,
                detail={
                    "code": "invalid_schema",
                    "message": "schema is too deeply nested or contains too many nodes.",
                },
            )
        if isinstance(item, dict):
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)

    visit(value, 0)
    return value


async def extract_arguments(body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    allowed = {
        "api_key_id",
        "urls",
        "prompt",
        "schema",
        "effort",
        "max_charge_credits",
        "quote_revision",
    }
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise HTTPException(
            422,
            detail={
                "code": "invalid_input",
                "message": "Unsupported fields: " + ", ".join(unknown),
            },
        )

    urls = body.get("urls")
    if not isinstance(urls, list) or not 1 <= len(urls) <= 20:
        raise HTTPException(
            422,
            detail={
                "code": "invalid_urls",
                "message": "Provide between 1 and 20 public HTTP(S) URLs.",
            },
        )
    normalized_urls: list[str] = []
    seen: set[str] = set()
    for value in urls:
        if not isinstance(value, str):
            raise HTTPException(
                422,
                detail={"code": "invalid_urls", "message": "Every URL must be a string."},
            )
        url = value.strip()
        if not url or len(url.encode()) > 4096:
            raise HTTPException(
                422,
                detail={
                    "code": "invalid_urls",
                    "message": "Each URL must contain 1–4096 UTF-8 bytes.",
                },
            )
        if url not in seen:
            seen.add(url)
            normalized_urls.append(url)
    if not normalized_urls:
        raise HTTPException(
            422,
            detail={"code": "invalid_urls", "message": "At least one unique URL is required."},
        )

    try:
        await asyncio.gather(
            *(asyncio.to_thread(validate_public_http_url, url) for url in normalized_urls)
        )
    except ResolutionUnavailable as exc:
        raise HTTPException(
            503,
            detail={"code": "resolver_busy", "message": "URL resolution is unavailable."},
        ) from exc
    except PolicyError as exc:
        raise HTTPException(
            422,
            detail={"code": "target_blocked", "message": str(exc)},
        ) from exc

    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not 3 <= len(prompt.strip()) <= 4000:
        raise HTTPException(
            422,
            detail={
                "code": "invalid_prompt",
                "message": "Extraction instructions must contain 3–4000 characters.",
            },
        )
    prompt = prompt.strip()
    schema = _bounded_schema(body.get("schema"))
    effort = str(body.get("effort") or "medium").strip().lower()
    if effort not in _EFFORT_CREDITS:
        raise HTTPException(
            422,
            detail={
                "code": "invalid_effort",
                "message": "effort must be low, medium, or high.",
            },
        )

    provider_arguments: dict[str, Any] = {
        "urls": normalized_urls,
        "prompt": prompt,
        "effort": effort,
        "maxCredits": _EFFORT_CREDITS[effort],
        "zeroDataRetention": True,
    }
    if schema is not None:
        provider_arguments["schema"] = schema

    metered: dict[str, Any] = {
        "capability": _CAPABILITY,
        "arguments": provider_arguments,
    }
    for name in ("max_charge_credits", "quote_revision"):
        if name in body:
            metered[name] = body[name]

    product = {
        "urls": normalized_urls,
        "prompt": prompt,
        "schema": schema,
        "effort": effort,
        "source_count": len(normalized_urls),
    }
    return metered, product


@router.post("/api/extract/quote")
async def quote_extract(request: Request):
    body = await _body(request)
    identity = await run_in_threadpool(_playground_identity, request, body)
    metered, product = await extract_arguments(body)
    quote_arguments = {
        "capability": metered["capability"],
        "arguments": metered["arguments"],
    }
    try:
        quote = await run_in_threadpool(
            execution_quote,
            store,
            identity,
            "mesh_capability_execute",
            quote_arguments,
        )
        quote["extract"] = {
            "source_count": product["source_count"],
            "effort": product["effort"],
            "schema_provided": product["schema"] is not None,
            "asynchronous": True,
        }
        return _response(quote)
    except ControlError as exc:
        raise _error(exc) from exc


@router.post("/api/extract/runs", status_code=202)
async def create_extract_run(request: Request):
    body = await _body(request)
    identity = await run_in_threadpool(_playground_identity, request, body)
    metered, _product = await extract_arguments(body)
    try:
        run = await run_in_threadpool(
            runs.create,
            identity,
            request.headers.get("idempotency-key", ""),
            _CAPABILITY,
            metered,
        )
        # Launch a newly queued run immediately so the user does not wait for the
        # scheduler just to start upstream work. The durable row and reservation
        # already exist; a lost response can be retried with the same idempotency key.
        if run.get("status") == "queued":
            await dispatch_capability_run(runs, run_id=run["id"])
            run = await run_in_threadpool(runs.get, identity.user_id, run["id"])
        return _response({"run": run}, status_code=202)
    except ControlError as exc:
        raise _error(exc) from exc


@router.get("/api/extract/runs")
def list_extract_runs(
    request: Request,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
):
    try:
        return _response(runs.list(_owner(request), limit, offset))
    except ControlError as exc:
        raise _error(exc) from exc


@router.get("/api/extract/runs/{run_id}")
def get_extract_run(request: Request, run_id: str):
    try:
        return _response({"run": runs.get(_owner(request), run_id)})
    except ControlError as exc:
        raise _error(exc) from exc


@router.post("/api/extract/runs/{run_id}/cancel")
def cancel_extract_run(request: Request, run_id: str):
    try:
        return _response({"run": runs.cancel(_owner(request, write=True), run_id)})
    except ControlError as exc:
        raise _error(exc) from exc


@router.get("/api/internal/capability-runs/tick")
async def capability_run_tick(request: Request):
    await _scheduler_authorized(request.headers.get("authorization"))
    return await dispatch_capability_run(runs)
