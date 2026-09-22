from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, HTTPException, Request

from .control_api import _require_user, _require_verified
from .game_catalog import build_game_adapters
from .capability_economics import settle_measured_cost
from .control_store import ControlError
from .playground_api import _playground_identity, store
from .tool_mcp import get_capability_registry, get_tool_mesh

router = APIRouter()

_LOCAL_TOOLS = {
    "mlbb.reference.heroes": "mlbb-heroes",
    "mlbb.reference.hero": "mlbb-hero",
    "mlbb.reference.items": "mlbb-items",
    "game.matches.analyze": "match-analysis",
    "league.reference.champions": "league-champions",
    "league.reference.items": "league-items",
}


@router.get("/api/games")
async def games(request: Request, q: str = ""):
    _require_verified(_require_user(request))
    adapters = build_game_adapters(get_capability_registry().capabilities)
    statuses = await get_tool_mesh().provider_status()
    query = q.strip().casefold()[:100]
    rows = [adapter.to_dict(statuses) for adapter in adapters.values()
            if not query or query in adapter.name.casefold() or query in adapter.game_id]
    return {"games": rows}


@router.get("/api/games/{game_id}")
async def game_detail(request: Request, game_id: str):
    _require_verified(_require_user(request))
    adapter = build_game_adapters(get_capability_registry().capabilities).get(game_id)
    if not adapter:
        raise HTTPException(status_code=404, detail={"code": "unknown_game", "message": "Game adapter is unavailable."})
    statuses = await get_tool_mesh().provider_status()
    return {"game": adapter.to_dict(statuses, details=True)}


@router.post("/api/games/{game_id}/tools/{capability_id}")
async def run_local_game_tool(request: Request, game_id: str, capability_id: str):
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": "Expected JSON input."}) from exc
    if not isinstance(body, dict) or not isinstance(body.get("arguments"), dict):
        raise HTTPException(status_code=400, detail={"message": "Expected arguments as an object."})
    adapters = build_game_adapters(get_capability_registry().capabilities)
    adapter = adapters.get(game_id)
    tool_id = _LOCAL_TOOLS.get(capability_id)
    if not adapter or not tool_id or capability_id not in {cap.id for cap in adapter.capabilities}:
        raise HTTPException(status_code=404, detail={"message": "Game tool not found."})
    identity = _playground_identity(request, body)
    arguments = dict(body["arguments"])
    if tool_id == "match-analysis":
        arguments["game"] = adapter.name
    request_id = "req_" + uuid.uuid4().hex
    tool_name = "gamecore:" + tool_id
    try:
        reserved = store.reserve_tool_call(
            identity=identity, request_id=request_id, tool_name=tool_name,
            arguments=arguments, input_bytes=len(json.dumps(body).encode()),
        )
    except ControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.detail}) from exc
    started = time.monotonic()
    status = "error"
    output_bytes = 0
    try:
        result = await get_tool_mesh().providers["gamecore"].execute(tool_id, arguments)
        response = {"ok": True, "request_id": request_id, "result": result["data"],
                    "usage": {"credits_charged": 1, "credits_reserved": reserved}}
        output_bytes = len(json.dumps(response).encode())
        status = "ok"
        return response
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "request_id": request_id}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail={"message": str(exc), "request_id": request_id}) from exc
    finally:
        store.finish_usage(
            request_id, status=status, latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            output_bytes=output_bytes,
            actual_credits=settle_measured_cost(tool_name, arguments, identity.plan_slug,
                                                reserved_credits=reserved, execution_usage={"completed": status == "ok"}),
            execution_usage={"completed": status == "ok", "counters": {"local_operations": 1}},
        )
