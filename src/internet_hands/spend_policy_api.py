"""Session-owned spend controls; execution keys cannot raise their own caps."""
import json

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from . import control_api
from .control_store import ControlError
from .spend_policies import SpendPolicyStore

router = APIRouter()
policies = SpendPolicyStore(control_api.store)


def _response(data):
    return JSONResponse(jsonable_encoder(data), headers={'Cache-Control':'no-store'})


def _owner(request):
    return control_api._require_user(request)['id']


async def _body(request):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw)+len(chunk)>4096:
            raise ControlError('request_too_large','Spending-limit requests are limited to 4 KB.',413)
        raw.extend(chunk)
    try:
        return json.loads(raw)
    except (ValueError,UnicodeDecodeError) as exc:
        raise ControlError('invalid_json','Expected a JSON object.',400) from exc


@router.get('/api/spend-policy')
def account_policy(request: Request):
    owner = _owner(request)
    try:
        return _response(policies.get(owner))
    except ControlError as exc:
        raise control_api._json_error(exc) from exc


@router.get('/api/api-keys/{key_id}/spend-policy')
def key_policy(key_id: str, request: Request):
    owner = _owner(request)
    try:
        if key_id=='account':
            raise ControlError('api_key_not_found','API key not found for this account.',404)
        return _response(policies.get(owner,key_id))
    except ControlError as exc:
        raise control_api._json_error(exc) from exc


async def _save(request, scope, *, key_scope=False):
    owner = _owner(request)
    try:
        if key_scope and scope=='account':
            raise ControlError('api_key_not_found','API key not found for this account.',404)
        body = await _body(request)
        return _response(await run_in_threadpool(policies.put,owner,scope,body))
    except ControlError as exc:
        raise control_api._json_error(exc) from exc


@router.put('/api/spend-policy')
async def save_account_policy(request: Request):
    return await _save(request,'account')


@router.put('/api/api-keys/{key_id}/spend-policy')
async def save_key_policy(key_id: str, request: Request):
    return await _save(request,key_id,key_scope=True)
