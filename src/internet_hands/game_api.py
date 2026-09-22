from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .control_api import _require_user, _require_verified
from .game_catalog import build_game_adapters
from .tool_mcp import get_capability_registry, get_tool_mesh

router = APIRouter()


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
