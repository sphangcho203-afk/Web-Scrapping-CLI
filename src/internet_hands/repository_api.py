from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .capability_economics import settle_measured_cost
from .control_store import ControlError
from .github_public_provider import PublicRepositoryError
from .playground_api import _playground_identity, store
from .tool_mcp import get_tool_mesh

router = APIRouter()


async def _execute(request: Request, operation: str) -> dict[str, Any]:
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_json", "message": "Expected a JSON object."}) from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail={"code": "invalid_input", "message": "Expected a JSON object."})
    identity = _playground_identity(request, body)
    field = "query" if operation == "search" else "repository"
    value = str(body.get(field) or "").strip()
    if not value or len(value) > (160 if operation == "search" else 240):
        raise HTTPException(status_code=400, detail={"code": "invalid_input", "message": f"Enter a valid {field}."})

    request_id = f"req_{uuid.uuid4().hex}"
    tool_name = f"repo:{operation}"
    arguments = {field: value}
    try:
        reserved = store.reserve_tool_call(
            identity=identity, request_id=request_id, tool_name=tool_name,
            arguments=arguments, input_bytes=len(json.dumps(body).encode()),
        )
    except ControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.detail}) from exc

    calls: list[str] = []
    started = time.monotonic()
    status = "error"
    output_bytes = 0
    try:
        provider = get_tool_mesh().providers["githubpublic"]
        result = await provider.execute(operation, {field: value, "_usage_calls": calls})
        measured = {"completed": True, "counters": {"github_api_calls": len(calls)}}
        charged = settle_measured_cost(tool_name, arguments, identity.plan_slug,
                                       reserved_credits=reserved, execution_usage=measured)
        response = {"ok": True, "request_id": request_id,
                    "usage": {"credits_charged": charged, "credits_reserved": reserved,
                              "github_api_calls": len(calls), "metered": True},
                    "result": result["data"]}
        output_bytes = len(json.dumps(response, default=str).encode())
        status = "ok"
        return response
    except PublicRepositoryError as exc:
        raise HTTPException(status_code=exc.status_code,
                            detail={"code": "repository_unavailable", "message": str(exc), "request_id": request_id}) from exc
    finally:
        elapsed = max(0, int((time.monotonic() - started) * 1000))
        measured = {"completed": status == "ok", "counters": {"github_api_calls": len(calls)},
                    "provider_usage": [{"provider": "github", "operation": "rest", "credits_used": None,
                                        "status": status} for _ in calls]}
        store.finish_usage(request_id, status=status, latency_ms=elapsed, output_bytes=output_bytes,
                           actual_credits=settle_measured_cost(
                               tool_name, arguments, identity.plan_slug,
                               reserved_credits=reserved, execution_usage=measured),
                           execution_usage=measured)


@router.post("/api/repos/search")
async def search_repositories(request: Request):
    return await _execute(request, "search")


@router.post("/api/repos/inspect")
async def inspect_repository(request: Request):
    return await _execute(request, "inspect")
