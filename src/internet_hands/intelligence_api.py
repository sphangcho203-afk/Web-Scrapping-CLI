"""Authenticated REST entry point for first-party intelligence-fabric tools."""
from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, HTTPException, Request

from .capability_economics import settle_measured_cost
from .control_store import ControlError
from .execution_meter import execution_usage_snapshot, reset_execution_meter, start_execution_meter
from .playground_api import _playground_identity, store
from .tool_mcp import get_tool_mesh

router = APIRouter()
_ALLOWED = {"smart-fetch", "discover-interfaces", "search-extract"}


@router.post("/api/intelligence/{operation}")
async def execute_intelligence(request: Request, operation: str):
    if operation not in _ALLOWED:
        raise HTTPException(status_code=404, detail={"message": "unknown intelligence operation"})
    try:
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("arguments"), dict):
            raise TypeError("Expected arguments as an object")
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc

    identity = _playground_identity(request, body)
    call = {"ref": f"intelligence:{operation}", "arguments": body["arguments"]}
    request_id = "req_" + uuid.uuid4().hex
    try:
        reserved = store.reserve_tool_call(
            identity=identity,
            request_id=request_id,
            tool_name="mesh_execute",
            arguments=call,
            input_bytes=len(json.dumps(body).encode()),
        )
    except ControlError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.detail},
        ) from exc

    token = start_execution_meter()
    started = time.monotonic()
    completed = False
    output_bytes = 0
    try:
        result = await get_tool_mesh().execute(
            call["ref"],
            body["arguments"],
            timeout_seconds=min(int(body.get("timeout_seconds", 60)), 60),
        )
        completed = result.get("status") == "completed"
        usage = execution_usage_snapshot()
        charge = settle_measured_cost(
            "mesh_execute",
            call,
            identity.plan_slug,
            reserved_credits=reserved,
            execution_usage=usage,
        )
        response = {
            "ok": completed,
            "request_id": request_id,
            "result": result.get("data"),
            "usage": {
                "credits_reserved": reserved,
                "credits_charged": charge,
            },
        }
        output_bytes = len(json.dumps(response, default=str).encode())
        if not completed:
            raise HTTPException(
                status_code=502,
                detail={**response, "message": result.get("error") or "intelligence operation failed"},
            )
        return response
    finally:
        usage = {**execution_usage_snapshot(), "completed": completed}
        try:
            store.finish_usage(
                request_id,
                status="ok" if completed else "error",
                latency_ms=int((time.monotonic() - started) * 1000),
                output_bytes=output_bytes,
                actual_credits=settle_measured_cost(
                    "mesh_execute",
                    call,
                    identity.plan_slug,
                    reserved_credits=reserved,
                    execution_usage=usage,
                ),
                execution_usage=usage,
            )
        finally:
            reset_execution_meter(token)
