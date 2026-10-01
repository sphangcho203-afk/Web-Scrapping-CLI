"""Operator-only cost facts use the existing service-token/OIDC boundary."""
from decimal import Decimal

from fastapi import APIRouter, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .control_api import store
from .control_store import ControlError
from .cost_events import CostEventStore
from .cost_rates import CostRateStore
from .datasets_api import _error
from .monitor_executor import _scheduler_authorized

router = APIRouter()
costs = CostEventStore(store)
rates = CostRateStore(store)


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


async def _body(request):
    import json

    raw=bytearray()
    async for chunk in request.stream():
        if len(raw)+len(chunk)>8192:
            raise ControlError('request_too_large','Rate requests are limited to 8 KB.',413)
        raw.extend(chunk)
    try:
        body=json.loads(raw)
    except (ValueError,UnicodeDecodeError) as exc:
        raise ControlError('invalid_json','Expected a JSON object.',400) from exc
    if not isinstance(body,dict):
        raise ControlError('invalid_json','Expected a JSON object.',422)
    return body


def _response(data,status=200):
    return JSONResponse(jsonable_encoder(data,custom_encoder={Decimal:str}),status_code=status,
                        headers={'Cache-Control':'no-store'})


@router.post('/api/internal/cost-rates',status_code=201)
async def create_rate(request: Request,authorization: str | None=Header(default=None)):
    await _scheduler_authorized(authorization)
    try:
        body=await _body(request)
        return _response({'rate':await run_in_threadpool(rates.create,body)},201)
    except ControlError as exc:
        raise _error(exc) from exc


@router.get('/api/internal/cost-rates')
async def list_rates(authorization: str | None=Header(default=None),
                     provider: str | None=Query(None,max_length=80),
                     limit: int=Query(100,ge=1,le=200),offset: int=Query(0,ge=0,le=100000)):
    await _scheduler_authorized(authorization)
    try:
        return _response(await run_in_threadpool(rates.list,provider,limit,offset))
    except ControlError as exc:
        raise _error(exc) from exc


@router.post('/api/internal/runs/{run_id}/economics/value')
async def value_run(run_id: str,request: Request,authorization: str | None=Header(default=None)):
    await _scheduler_authorized(authorization)
    try:
        body=await _body(request)
        if set(body)-{'rate_revision','dry_run','limit'}:
            raise ControlError('invalid_valuation','Unexpected valuation options.',422)
        data=await run_in_threadpool(rates.value_run,run_id,body.get('rate_revision'),
                    dry_run=body.get('dry_run',True),limit=body.get('limit',100))
        return _response(data)
    except ControlError as exc:
        raise _error(exc) from exc
