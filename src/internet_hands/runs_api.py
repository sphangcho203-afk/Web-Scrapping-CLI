"""Read-only receipts; existing specialized cancellation APIs remain authoritative."""
from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .control_store import ControlError
from .datasets_api import _error, _owner, store
from .run_envelope import RunEnvelopeStore

router = APIRouter()
runs = RunEnvelopeStore(store)


@router.get('/api/runs')
def list_runs(request: Request, limit: int = Query(25, ge=1, le=100),
              offset: int = Query(0, ge=0, le=100000)):
    owner = _owner(request)
    try:
        return _response(runs.list(owner, limit, offset))
    except ControlError as exc:
        raise _error(exc) from exc


@router.get('/api/runs/{run_id}')
def get_run(request: Request, run_id: str, after: int = Query(0, ge=0),
            limit: int = Query(100, ge=1, le=200)):
    owner = _owner(request)
    try:
        return _response(runs.get(owner, run_id, after, limit))
    except ControlError as exc:
        raise _error(exc) from exc


def _response(data):
    return JSONResponse(jsonable_encoder(data), headers={'Cache-Control':'no-store'})


@router.post('/api/runs/{run_id}/cancel')
def cancel_run(request: Request, run_id: str):
    owner = _owner(request, write=True)
    try:
        row = runs.get(owner, run_id, 0, 1)['run']
        if row['source_kind'] == 'crawl':
            from .crawl_runs import RunStore
            RunStore(store).cancel(owner, row['source_ref'])
        elif row['source_kind'] == 'capability':
            from .capability_runs import CapabilityRunStore
            CapabilityRunStore(store).cancel(owner, row['source_ref'])
        else:
            raise ControlError('run_not_cancellable', 'This execution has no durable cancellation contract.', 409)
        return _response(runs.get(owner, row['id'], 0, 100))
    except ControlError as exc:
        raise _error(exc) from exc
