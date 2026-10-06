"""Verified account controls and the existing scheduler boundary for change mail."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool

from .control_api import _require_user, _require_verified, store
from .control_store import ControlError
from .dataset_webhook_api import _response
from .datasets_api import _error
from .monitor_email_store import MonitorEmailStore
from .monitor_emails import AlertMailError, alert_mail_settings, dispatch_monitor_emails
from .monitor_executor import _scheduler_authorized

router = APIRouter()
emails = MonitorEmailStore(store)


def _available():
    try:
        alert_mail_settings()
        return True
    except AlertMailError:
        return False


@router.get("/api/monitors/{monitor_id}/email-alerts")
async def email_settings(request: Request, monitor_id: str):
    user = _require_user(request)
    try:
        data = await run_in_threadpool(emails.settings, user["id"], monitor_id)
        data["available"] = await run_in_threadpool(_available)
        return _response(data)
    except ControlError as exc:
        raise _error(exc) from exc


@router.put("/api/monitors/{monitor_id}/email-alerts")
async def configure_email_alerts(request: Request, monitor_id: str):
    user = _require_verified(_require_user(request))
    raw = await request.body()
    if len(raw) > 4000:
        raise HTTPException(413, detail="Email preferences are limited to 4 KB.")
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, detail="Expected a JSON object.") from exc
    if not isinstance(body, dict) or set(body) - {"enabled", "fields", "confirm_email"}:
        raise HTTPException(422, detail="Unsupported email preference inputs.")
    try:
        # Establish ownership before consulting provider configuration.
        await run_in_threadpool(emails.settings, user["id"], monitor_id)
        if body.get("enabled") is True:
            await run_in_threadpool(alert_mail_settings)
        data = await run_in_threadpool(emails.configure, user["id"], monitor_id,
            enabled=body.get("enabled"), fields=body.get("fields"), confirm_email=body.get("confirm_email", False))
        data["available"] = await run_in_threadpool(_available)
        return _response(data)
    except AlertMailError as exc:
        raise HTTPException(503, detail=str(exc)) from exc
    except ControlError as exc:
        raise _error(exc) from exc


@router.get("/api/monitors/{monitor_id}/email-alerts/deliveries")
def email_deliveries(request: Request, monitor_id: str, limit: int = Query(25, ge=1, le=100)):
    try:
        return _response(emails.history(_require_user(request)["id"], monitor_id, limit))
    except ControlError as exc:
        raise _error(exc) from exc


async def _run_owned(request, monitor_id, action, event_id=None):
    user = _require_verified(_require_user(request))
    try:
        await run_in_threadpool(emails.settings, user["id"], monitor_id)
        await run_in_threadpool(alert_mail_settings)
        if action == "test":
            event = await run_in_threadpool(emails.test_email, user["id"], monitor_id)
            event_id = event["id"]
        elif action == "retry":
            await run_in_threadpool(emails.retry, user["id"], monitor_id, event_id)
        else:
            await run_in_threadpool(emails.request_receipt, user["id"], monitor_id, event_id)
        await dispatch_monitor_emails(emails, event_id=event_id)
        return _response(await run_in_threadpool(emails.history, user["id"], monitor_id))
    except ControlError as exc:
        raise _error(exc) from exc
    except AlertMailError as exc:
        raise HTTPException(503, detail=str(exc)) from exc


@router.post("/api/monitors/{monitor_id}/email-alerts/test")
async def test_email(request: Request, monitor_id: str):
    return await _run_owned(request, monitor_id, "test")


@router.post("/api/monitors/{monitor_id}/email-alerts/deliveries/{event_id}/retry")
async def retry_email(request: Request, monitor_id: str, event_id: str):
    return await _run_owned(request, monitor_id, "retry", event_id)


@router.post("/api/monitors/{monitor_id}/email-alerts/deliveries/{event_id}/check")
async def check_email(request: Request, monitor_id: str, event_id: str):
    return await _run_owned(request, monitor_id, "check", event_id)


@router.get("/api/internal/monitor-emails/tick")
async def email_tick(request: Request):
    await _scheduler_authorized(request.headers.get("authorization"))
    return await asyncio.wait_for(dispatch_monitor_emails(emails), timeout=45)
