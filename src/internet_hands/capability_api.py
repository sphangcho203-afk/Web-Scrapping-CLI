"""Authenticated semantic-capability workbench.

This is a product-facing wrapper over the existing CapabilityRegistry. It does not
create a second provider router or billing system. The first tranche exposes only
read-only web capabilities that can complete synchronously inside an interactive
request; async capabilities remain discoverable but are explicitly non-runnable
until they have an owned durable job contract.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from psycopg import DatabaseError

from .auth import current_auth
from .capability_economics import settle_measured_cost
from .control_api import _require_user, _require_verified
from .control_store import (
    ControlError,
    raw_credits_from_wallet_reservation,
    wallet_credits_for_raw,
)
from .datasets import DatasetStore
from .execution_meter import execution_usage_snapshot, reset_execution_meter, start_execution_meter
from .playground_api import _playground_identity, execution_quote, store
from .tool_mcp import get_capability_registry

router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_BODY_BYTES = 128_000
_ASYNC_TAG = "async"


def _error(exc: ControlError) -> HTTPException:
    return HTTPException(exc.status_code, detail={"code": exc.code, "message": exc.detail})


async def _json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "input_too_large", "message": "Capability input must be at most 128 KB."},
        )
    try:
        body = json.loads(raw or b"{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_json", "message": "Expected a JSON object."},
        ) from exc
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_input", "message": "Expected a JSON object."},
        )
    return body


def _arguments(body: dict[str, Any]) -> dict[str, Any]:
    arguments = body.get("arguments")
    if not isinstance(arguments, dict):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_arguments", "message": "arguments must be a JSON object."},
        )
    return arguments


def _capability(capability_id: str):
    capability_id = capability_id.strip()
    capability = get_capability_registry().capabilities.get(capability_id)
    if capability is None or capability.pack != "web":
        raise HTTPException(
            status_code=404,
            detail={"code": "capability_not_found", "message": "This web capability is not registered."},
        )
    if not capability.read_only:
        raise HTTPException(
            status_code=409,
            detail={"code": "interactive_not_supported", "message": "Side-effecting capabilities are not available in the read-only workbench."},
        )
    return capability


async def _workbench_spec(capability_id: str) -> dict[str, Any]:
    capability = _capability(capability_id)
    resolved = await get_capability_registry().resolve(capability_id)
    available = [
        item for item in resolved.get("resolved") or []
        if item.get("available") and isinstance(item.get("tool"), dict)
    ]
    schemas = [item["tool"] for item in available]
    sync_tools = [tool for tool in schemas if _ASYNC_TAG not in set(tool.get("tags") or [])]
    interactive_ready = bool(sync_tools) and len(sync_tools) == len(schemas)
    schema_source = sync_tools[0] if interactive_ready else (schemas[0] if schemas else {})
    input_schema = capability.input_schema or schema_source.get("input_schema") or {
        "type": "object", "properties": {}
    }
    output_schema = capability.output_schema or schema_source.get("output_schema") or {}
    if not available:
        reason = "No configured execution route is currently available."
    elif not interactive_ready:
        reason = (
            "This capability currently resolves through an asynchronous provider job. "
            "OpenCrawl will expose it here after it has an owned durable job/polling contract."
        )
    else:
        reason = None
    return {
        "capability": {
            "id": capability.id,
            "name": capability.name,
            "description": capability.description,
            "pack": capability.pack,
            "tags": list(capability.tags),
            "read_only": capability.read_only,
            "input_schema": input_schema,
            "output_schema": output_schema,
        },
        "availability": {
            "interactive_ready": interactive_ready,
            "available_routes": len(available),
            "reason": reason,
        },
    }


def _dataset_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        values = data
    elif isinstance(data, dict):
        values = None
        for key in ("results", "items", "links", "records"):
            candidate = data.get(key)
            if isinstance(candidate, list):
                values = candidate
                break
        if values is None:
            values = [data]
    else:
        values = [data]

    rows: list[dict[str, Any]] = []
    for value in values:
        rows.append(dict(value) if isinstance(value, dict) else {"value": value})
    return rows


def _public_execution(capability_id: str, result: dict[str, Any]) -> dict[str, Any]:
    execution = result.get("execution") or {}
    return {
        "capability": capability_id,
        "status": execution.get("status") or ("failed" if result.get("error") else "completed"),
        "data": execution.get("data"),
        "duration_ms": result.get("duration_ms"),
        "route_attempts": [
            {"status": item.get("status"), "error": item.get("error")}
            for item in (result.get("attempts") or [])
        ],
        "error": execution.get("error") or result.get("error"),
    }


def _save_dataset(user_id: str, request_id: str, capability_id: str,
                  public_result: dict[str, Any], name: str) -> dict[str, Any]:
    payload = {
        **public_result,
        "records": _dataset_records(public_result.get("data")),
    }
    try:
        dataset = DatasetStore(store).save(
            user_id, request_id, f"capability:{capability_id}", payload, name
        )
        return {"dataset": dataset}
    except (ControlError, DatabaseError):
        logger.exception("Capability dataset persistence failed for run %s", request_id)
        return {
            "dataset": None,
            "warnings": [{
                "code": "dataset_not_saved",
                "message": (
                    "The capability completed but its output could not be saved. "
                    "Copy the result before leaving this page."
                ),
            }],
        }


@router.get("/api/capabilities")
def list_capabilities(
    request: Request,
    q: str = Query("", max_length=120),
    pack: str = Query("web", max_length=60),
    limit: int = Query(100, ge=1, le=100),
):
    _require_verified(_require_user(request))
    if pack != "web":
        raise HTTPException(
            status_code=400,
            detail={"code": "unsupported_pack", "message": "The browser workbench currently exposes the web capability pack."},
        )
    rows = get_capability_registry().list(query=q, pack=pack, limit=limit)["capabilities"]
    return {
        "capabilities": [{
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "pack": row["pack"],
            "tags": row.get("tags") or [],
            "read_only": bool(row.get("read_only", True)),
        } for row in rows]
    }


@router.get("/api/capabilities/{capability_id:path}")
async def capability_detail(request: Request, capability_id: str):
    _require_verified(_require_user(request))
    return await _workbench_spec(capability_id)


@router.post("/api/capabilities/{capability_id:path}/quote")
async def capability_quote(request: Request, capability_id: str, response: Response):
    body = await _json_body(request)
    arguments = _arguments(body)
    spec = await _workbench_spec(capability_id)
    if not spec["availability"]["interactive_ready"]:
        raise HTTPException(
            status_code=409,
            detail={"code": "interactive_not_ready", "message": spec["availability"]["reason"]},
        )
    identity = _playground_identity(request, body)
    metered = {"capability": capability_id, "arguments": arguments}
    response.headers["Cache-Control"] = "no-store"
    return execution_quote(store, identity, "mesh_capability_execute", metered)


@router.post("/api/capabilities/{capability_id:path}/run")
async def capability_run(request: Request, capability_id: str):
    body = await _json_body(request)
    arguments = _arguments(body)
    spec = await _workbench_spec(capability_id)
    if not spec["availability"]["interactive_ready"]:
        raise HTTPException(
            status_code=409,
            detail={"code": "interactive_not_ready", "message": spec["availability"]["reason"]},
        )
    identity = _playground_identity(request, body)
    request_id = "req_" + uuid.uuid4().hex
    metered: dict[str, Any] = {"capability": capability_id, "arguments": arguments}
    for field in ("max_charge_credits", "quote_revision"):
        if field in body:
            metered[field] = body[field]

    try:
        reserved = store.reserve_tool_call(
            identity=identity,
            request_id=request_id,
            tool_name="mesh_capability_execute",
            arguments=metered,
            input_bytes=len(json.dumps(body, default=str).encode()),
        )
        raw_reserved = raw_credits_from_wallet_reservation(reserved)
    except ControlError as exc:
        raise _error(exc) from exc

    meter = start_execution_meter()
    auth_token = current_auth.set(identity)
    started = time.monotonic()
    completed = False
    output_bytes = 0
    public_result: dict[str, Any] | None = None
    try:
        result = await get_capability_registry().execute(
            capability_id,
            arguments,
            wait_seconds=30,
            timeout_seconds=60,
        )
        public_result = _public_execution(capability_id, result)
        completed = public_result["status"] in {"completed", "ok"} and not public_result.get("error")
        usage_snapshot = {**execution_usage_snapshot(), "completed": completed}
        raw_charge = settle_measured_cost(
            "mesh_capability_execute",
            metered,
            identity.plan_slug,
            reserved_credits=raw_reserved,
            execution_usage=usage_snapshot,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
        )
        usage = {
            "credits_reserved": reserved,
            "credits_charged": wallet_credits_for_raw(raw_charge),
            "metered": True,
        }
        if not completed:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "capability_failed",
                    "message": public_result.get("error") or "No execution route completed successfully.",
                    "request_id": request_id,
                    "usage": usage,
                    "result": public_result,
                },
            )

        response = {
            "ok": True,
            "request_id": request_id,
            "result": public_result,
            "usage": usage,
        }
        response.update(_save_dataset(
            identity.user_id,
            request_id,
            capability_id,
            public_result,
            spec["capability"]["name"],
        ))
        output_bytes = len(json.dumps(response, default=str).encode())
        return response
    except HTTPException:
        raise
    except (ValueError, PermissionError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_capability_input", "message": str(exc), "request_id": request_id},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "capability_failed", "message": f"{type(exc).__name__}: {exc}", "request_id": request_id},
        ) from exc
    finally:
        elapsed = max(0, int((time.monotonic() - started) * 1000))
        execution_usage = {**execution_usage_snapshot(), "completed": completed}
        try:
            store.finish_usage(
                request_id,
                status="ok" if completed else "error",
                latency_ms=elapsed,
                output_bytes=output_bytes,
                actual_credits=settle_measured_cost(
                    "mesh_capability_execute",
                    metered,
                    identity.plan_slug,
                    reserved_credits=raw_reserved,
                    execution_usage=execution_usage,
                    latency_ms=elapsed,
                ),
                execution_usage=execution_usage,
            )
        finally:
            current_auth.reset(auth_token)
            reset_execution_meter(meter)
