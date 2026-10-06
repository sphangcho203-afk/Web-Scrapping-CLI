"""Guided product preview and owner-scoped scheduled field tracking."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from .content_monitors import content_identity, product_arguments
from .control_api import _require_user, _require_verified, store
from .control_store import ControlError
from .crawl_run_api import _response
from .crawl_run_worker import dispatch_run
from .crawl_runs import RunStore, public_run
from .datasets_api import _error, _owner
from .monitor_lifecycle import validate_monitor_spec
from .playground_api import _playground_identity, _request_credential, execution_quote
from .policy import PolicyError, ResolutionUnavailable, validate_public_http_url
from .product_data import product_fingerprint

router = APIRouter()


async def _body(request):
    raw = await request.body()
    if len(raw) > 16_000:
        raise HTTPException(413, detail="Product tracker requests are limited to 16 KB.")
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, detail="Expected a JSON object.") from exc
    if not isinstance(body, dict):
        raise HTTPException(422, detail="Expected a JSON object.")
    return body


def preview_arguments(body):
    if set(body) - {"url", "api_key_id", "max_charge_credits", "quote_revision"}:
        raise HTTPException(422, detail="Unsupported product preview inputs.")
    url = body.get("url")
    if not isinstance(url, str) or not url.strip() or len(url.strip()) > 2000:
        raise HTTPException(422, detail="Enter a public product URL of at most 2000 characters.")
    arguments = product_arguments(url.strip())
    for key in ("max_charge_credits", "quote_revision"):
        if key in body:
            arguments[key] = body[key]
    return arguments


async def _target(url):
    try:
        await asyncio.to_thread(validate_public_http_url, url)
    except ResolutionUnavailable as exc:
        raise HTTPException(503, detail="URL resolution is unavailable. Try again shortly.") from exc
    except PolicyError as exc:
        raise HTTPException(422, detail={"code": "target_blocked", "message": str(exc)}) from exc


@router.post("/api/product-tracker/quote")
async def quote_product(request: Request):
    body = await _body(request)
    identity = await run_in_threadpool(_playground_identity, request, body)
    arguments = preview_arguments(body)
    await _target(arguments["url"])
    try:
        return _response(await run_in_threadpool(execution_quote, store, identity, "playground:crawl", arguments))
    except ControlError as exc:
        raise _error(exc) from exc


@router.post("/api/product-tracker/runs", status_code=202)
async def preview_product(request: Request):
    body = await _body(request)
    identity = await run_in_threadpool(_playground_identity, request, body)
    arguments = preview_arguments(body)
    await _target(arguments["url"])
    runs = RunStore(store)
    try:
        run = await run_in_threadpool(runs.create, identity, request.headers.get("idempotency-key", ""), arguments)
        if run["status"] == "queued":
            await dispatch_run(runs, run_id=run["id"])
        return _response(await run_in_threadpool(product_run, identity.user_id, run["id"]), 202)
    except ControlError as exc:
        raise _error(exc) from exc


def product_run(owner, run_id):
    store.ensure_schema()
    with store._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM ih_crawl_runs WHERE id=%s AND user_id=%s", (run_id, owner))
        row = cur.fetchone()
        if not row or not row["arguments"].get("include_products"):
            raise ControlError("run_not_found", "Product preview not found for this account.", 404)
        products = []
        if row["dataset_id"]:
            cur.execute("SELECT rows FROM ih_datasets WHERE id=%s AND user_id=%s", (row["dataset_id"], owner))
            dataset = cur.fetchone()
            products = dataset["rows"] if dataset else []
        return {"run": public_run(row), "products": products}


@router.get("/api/product-tracker/runs/{run_id}")
def get_product_run(request: Request, run_id: str):
    try:
        return _response(product_run(_owner(request), run_id))
    except ControlError as exc:
        raise _error(exc) from exc


def start_tracking(owner, body):
    if set(body) - {"run_id", "name", "interval_minutes", "fields", "max_charge_credits", "confirm_recurring"}:
        raise HTTPException(422, detail="Unsupported tracking inputs.")
    if body.get("confirm_recurring") is not True:
        raise HTTPException(422, detail="Confirm recurring credit charges before enabling tracking.")
    run_id = body.get("run_id")
    if not isinstance(run_id, str) or len(run_id) > 120:
        raise HTTPException(422, detail="A completed product preview is required.")
    store.ensure_schema()
    with store._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM ih_users WHERE id=%s FOR UPDATE", (owner,))
        cur.execute("""SELECT r.*,u.api_key_id FROM ih_crawl_runs r
            JOIN ih_usage_events u ON u.request_id=r.request_id
            WHERE r.id=%s AND r.user_id=%s""", (run_id, owner))
        run = cur.fetchone()
        if not run or not run["arguments"].get("include_products"):
            raise ControlError("run_not_found", "Product preview not found for this account.", 404)
        if run["status"] != "completed" or not run["dataset_id"]:
            raise ControlError("preview_required", "Complete a successful preview before enabling tracking.", 409)
        cur.execute("SELECT * FROM ih_datasets WHERE id=%s AND user_id=%s FOR SHARE", (run["dataset_id"], owner))
        dataset = cur.fetchone()
        if not dataset or not dataset["rows"]:
            raise ControlError("preview_required", "The preview dataset is unavailable. Collect another preview.", 409)
        spec = validate_monitor_spec({"name": body.get("name"), "type": "product",
            "target": run["arguments"]["url"], "interval_minutes": body.get("interval_minutes", 1440),
            "config": {"api_key_id": run["api_key_id"], "preview_run_id": run_id,
                "fields": body.get("fields", ["price", "availability"]),
                "max_charge_credits": body.get("max_charge_credits", run["credits_reserved"])}})
        content_identity(store, owner, spec["config"])
        # One preview can enable one tracker. Account lock makes concurrent retries safe.
        cur.execute("SELECT * FROM ih_monitors WHERE user_id=%s AND type='product' AND config->>'preview_run_id'=%s",
                    (owner, run_id))
        existing = cur.fetchone()
        if existing:
            if any(existing[key] != spec[key] for key in ("name", "target", "interval_minutes", "config")):
                raise ControlError("idempotency_conflict", "This preview already enabled a tracker. Edit it in Monitors.", 409)
            return dict(existing)
        monitor = store.create_monitor(user_id=owner, name=spec["name"], monitor_type="product", target=spec["target"],
            interval_minutes=spec["interval_minutes"], config=spec["config"], transaction=conn)
        cur.execute("""UPDATE ih_monitors SET baseline_hash=%s,baseline_dataset_id=%s,
            last_status='baseline',last_checked_at=%s,next_check_at=now()+(interval_minutes || ' minutes')::interval
            WHERE id=%s RETURNING *""", (product_fingerprint(dataset["rows"], spec["config"]["fields"]),
                dataset["id"], dataset["created_at"], monitor["id"]))
        return dict(cur.fetchone())


@router.post("/api/product-trackers", status_code=201)
async def create_tracker(request: Request):
    if not _request_credential(request):
        _require_verified(_require_user(request))
    owner = _owner(request, write=True)
    body = await _body(request)
    try:
        return _response({"monitor": await run_in_threadpool(start_tracking, owner, body)}, 201)
    except ControlError as exc:
        raise _error(exc) from exc
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "invalid_monitor", "message": str(exc)}) from exc
