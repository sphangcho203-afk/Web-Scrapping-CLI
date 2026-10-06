from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .control_api import store
from .control_store import ControlError
from .dataset_webhook_store import WebhookStore
from .dataset_webhooks import dispatch_webhooks
from .datasets_api import _error, _owner
from .monitor_executor import _scheduler_authorized
from .policy import PolicyError
from .totp import encryption_configured

router = APIRouter()
webhooks = WebhookStore(store)


def _response(data: dict) -> JSONResponse:
    from fastapi.encoders import jsonable_encoder
    return JSONResponse(jsonable_encoder(data), headers={"Cache-Control": "no-store"})


@router.get("/api/dataset-webhook")
def webhook_settings(request: Request):
    user_id = _owner(request)
    return _response({"endpoint": webhooks.endpoint(user_id), "available": encryption_configured()})


@router.put("/api/dataset-webhook")
async def configure_webhook(request: Request):
    user_id = _owner(request, write=True)
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, detail="Expected a JSON object.") from exc
    if not isinstance(body, dict) or not isinstance(body.get("url"), str):
        raise HTTPException(422, detail="A webhook URL is required.")
    enabled, rotate = body.get("enabled", True), body.get("rotate_secret", False)
    if not isinstance(enabled, bool) or not isinstance(rotate, bool):
        raise HTTPException(422, detail="enabled and rotate_secret must be booleans.")
    try:
        return _response(webhooks.configure(user_id, body["url"].strip(), enabled, rotate))
    except PolicyError as exc:
        raise HTTPException(422, detail={"code": "invalid_webhook_url", "message": str(exc)}) from exc
    except ControlError as exc:
        raise _error(exc) from exc


@router.delete("/api/dataset-webhook")
def delete_webhook(request: Request):
    webhooks.delete_endpoint(_owner(request, write=True))
    return _response({"deleted": True})


@router.get("/api/dataset-webhook/deliveries")
def webhook_deliveries(request: Request, limit: int = Query(25, ge=1, le=100),
                       offset: int = Query(0, ge=0, le=100000)):
    return _response(webhooks.history(_owner(request), limit, offset))


@router.post("/api/dataset-webhook/deliveries/{event_id}/retry")
def retry_webhook(request: Request, event_id: str):
    user_id = _owner(request, write=True)
    try:
        return _response({"delivery": webhooks.retry(user_id, event_id)})
    except ControlError as exc:
        raise _error(exc) from exc


@router.get("/api/internal/dataset-webhooks/tick")
async def webhook_tick(request: Request):
    await _scheduler_authorized(request.headers.get("authorization"))
    return await dispatch_webhooks(webhooks)
