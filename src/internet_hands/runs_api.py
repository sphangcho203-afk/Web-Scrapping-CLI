"""Read-only receipts; existing specialized cancellation APIs remain authoritative."""
from fastapi import APIRouter, Query, Request

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
        return runs.list(owner, limit, offset)
    except ControlError as exc:
        raise _error(exc) from exc


@router.get('/api/runs/{run_id}')
def get_run(request: Request, run_id: str, after: int = Query(0, ge=0),
            limit: int = Query(100, ge=1, le=200)):
    owner = _owner(request)
    try:
        return runs.get(owner, run_id, after, limit)
    except ControlError as exc:
        raise _error(exc) from exc
