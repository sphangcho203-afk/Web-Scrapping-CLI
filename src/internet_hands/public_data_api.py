"""Authenticated dashboard entry point for the same public-data mesh tools."""
from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, HTTPException, Request

from .capability_economics import settle_measured_cost
from .control_store import ControlError
from .execution_meter import execution_usage_snapshot, reset_execution_meter, start_execution_meter
from .playground_api import _playground_identity, store
from .public_data_provider import request_budget
from .tool_mcp import get_tool_mesh

router = APIRouter()


@router.post("/api/public-data/{operation}")
async def execute_public_data(request: Request, operation: str):
    try:
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("arguments"), dict):
            raise TypeError("Expected arguments as an object")
        request_budget(operation, body["arguments"])
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    identity = _playground_identity(request, body)
    arguments = {"ref": f"publicdata:{operation}", "arguments": body["arguments"]}
    request_id = "req_" + uuid.uuid4().hex
    try:
        reserved = store.reserve_tool_call(identity=identity, request_id=request_id, tool_name="mesh_execute",
                                           arguments=arguments, input_bytes=len(json.dumps(body).encode()))
    except ControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.detail}) from exc
    token = start_execution_meter()
    started = time.monotonic()
    completed, output_bytes = False, 0
    try:
        result = await get_tool_mesh().execute(arguments["ref"], body["arguments"], timeout_seconds=25)
        completed = result["status"] == "completed"
        charge = settle_measured_cost("mesh_execute", arguments, identity.plan_slug,
                                      reserved_credits=reserved, execution_usage=execution_usage_snapshot())
        response = {"ok": completed, "request_id": request_id, "result": result.get("data"),
                    "usage": {"credits_reserved": reserved, "credits_charged": charge}}
        output_bytes = len(json.dumps(response, default=str).encode())
        if not completed:
            raise HTTPException(status_code=502, detail={**response, "message": result.get("error") or "Public sources are unavailable."})
        return response
    finally:
        usage = {**execution_usage_snapshot(), "completed": completed}
        try:
            store.finish_usage(request_id, status="ok" if completed else "error",
                               latency_ms=int((time.monotonic() - started) * 1000), output_bytes=output_bytes,
                               actual_credits=settle_measured_cost("mesh_execute", arguments, identity.plan_slug,
                                                                  reserved_credits=reserved, execution_usage=usage),
                               execution_usage=usage)
        finally:
            reset_execution_meter(token)
