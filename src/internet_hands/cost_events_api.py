"""Operator-only cost facts use the existing service-token/OIDC boundary."""
from decimal import Decimal

from fastapi import APIRouter, Header, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .control_api import store
from .control_store import ControlError
from .cost_events import CostEventStore
from .datasets_api import _error
from .monitor_executor import _scheduler_authorized

router = APIRouter()
costs = CostEventStore(store)


@router.get('/api/internal/runs/{run_id}/economics')
async def run_economics(run_id: str, authorization: str | None = Header(default=None),
                        limit: int = Query(100,ge=1,le=200), offset: int = Query(0,ge=0,le=100000)):
    await _scheduler_authorized(authorization)
    try:
        data = await run_in_threadpool(costs.for_run,run_id,limit,offset)
        return JSONResponse(jsonable_encoder(data,custom_encoder={Decimal:str}),
                            headers={'Cache-Control':'no-store'})
    except ControlError as exc:
        raise _error(exc) from exc
