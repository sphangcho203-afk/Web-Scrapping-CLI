from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from .control_api import _require_user, store
from .control_store import ControlError
from .usage_intelligence import UsageIntelligence

router = APIRouter()


@router.get("/api/usage/intelligence")
def usage_intelligence(
    request: Request,
    window: str = Query("30d"),
    recent_limit: int = Query(12, ge=1, le=50),
):
    user = _require_user(request)
    try:
        return UsageIntelligence(store).snapshot(user["id"], window=window, recent_limit=recent_limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_usage_window", "message": str(exc)}) from exc
    except ControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.detail}) from exc
