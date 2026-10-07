"""Owned, explicitly consented foreground Sandbox executions from the dashboard."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from .auth import current_auth
from .capability_economics import settle_measured_cost
from .control_api import _require_user, _require_verified
from .control_store import ControlError, raw_credits_from_wallet_reservation, wallet_credits_for_raw
from .execution_meter import execution_usage_snapshot, reset_execution_meter, start_execution_meter
from .playground_api import (
    _playground_identity,
    _request_credential,
    execution_quote,
    playground_body,
    store,
)
from .tool_mcp import get_tool_mesh

router = APIRouter()
_REF = "nativesandbox:exec"
_FIELDS = {"api_key_id", "command", "timeout_seconds", "allow_execution", "max_charge_credits", "quote_revision"}


def _error(code: str, message: str, status: int = 422) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


async def _inputs(request: Request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise _error("invalid_content_type", "Use application/json.", 415)
    body, raw = await playground_body(request)
    if not _request_credential(request):
        _require_verified(_require_user(request))
        if request.headers.get("origin") != str(request.base_url).rstrip("/"):
            raise _error("origin_required", "Dashboard execution requires a same-origin request.", 403)
    identity = _playground_identity(request, body)
    if set(body) - _FIELDS:
        raise _error("invalid_input", "Unsupported Sandbox input fields.")
    command = body.get("command")
    if not isinstance(command, str) or not command.strip() or len(command) > 50_000 or "\x00" in command:
        raise _error("invalid_command", "Provide a command of 1–50,000 characters without null bytes.")
    timeout = body.get("timeout_seconds", 10)
    if type(timeout) is not int or not 1 <= timeout <= 15:
        raise _error("invalid_timeout", "Interactive command timeout must be 1–15 seconds.")
    metered: dict[str, Any] = {
        "ref": _REF, "arguments": {"command": command, "timeout_seconds": timeout, "background": False},
    }
    for field in ("max_charge_credits", "quote_revision"):
        if field in body:
            metered[field] = body[field]
    return identity, body, raw, metered


async def _ready() -> None:
    descriptor = await get_tool_mesh().describe(_REF)
    if not (descriptor.get("metadata") or {}).get("configured"):
        raise _error("sandbox_unavailable", "Sandbox execution is unavailable. No credits were reserved.", 409)


@router.post("/api/sandbox/quote")
async def sandbox_quote(request: Request, response: Response):
    identity, _, _, metered = await _inputs(request)
    await _ready()
    response.headers["Cache-Control"] = "no-store"
    try:
        return execution_quote(store, identity, "mesh_execute", metered)
    except ControlError as exc:
        raise _error(exc.code, exc.detail, exc.status_code) from exc


@router.post("/api/sandbox/run")
async def sandbox_run(request: Request, response: Response):
    identity, body, raw, metered = await _inputs(request)
    if body.get("allow_execution") is not True:
        raise _error("execution_consent_required", "Confirm isolated command execution before running.", 403)
    cap = body.get("max_charge_credits")
    revision = body.get("quote_revision")
    if type(cap) is not int or not 0 <= cap <= 1_000_000_000:
        raise _error("spend_limit_required", "Set a maximum credit charge before running.")
    if not isinstance(revision, str) or len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
        raise _error("quote_required", "Review a current quote before running.")
    await _ready()
    request_id = "req_" + uuid.uuid4().hex
    try:
        reserved = store.reserve_tool_call(
            identity=identity, request_id=request_id, tool_name="mesh_execute",
            arguments=metered, input_bytes=len(raw),
        )
    except ControlError as exc:
        raise _error(exc.code, exc.detail, exc.status_code) from exc
    meter = start_execution_meter()
    auth_token = current_auth.set(identity)
    started = time.monotonic()
    result: dict[str, Any] = {"status": "failed", "error": "Sandbox execution did not complete."}
    completed = False
    try:
        result = await get_tool_mesh().execute(_REF, metered["arguments"], timeout_seconds=45)
        completed = result.get("status") == "completed" and not result.get("error")
    except Exception:  # noqa: BLE001 - return a bounded failure and settle before responding
        result = {"status": "failed", "error": "Sandbox execution failed. Check this run before retrying."}
    finally:
        try:
            elapsed = max(0, int((time.monotonic() - started) * 1000))
            execution_usage = {**execution_usage_snapshot(), "completed": completed}
            charge = settle_measured_cost(
                "mesh_execute", metered, identity.plan_slug,
                reserved_credits=raw_credits_from_wallet_reservation(reserved),
                execution_usage=execution_usage, latency_ms=elapsed,
            )
            store.finish_usage(
                request_id, status="ok" if completed else "error", latency_ms=elapsed,
                output_bytes=len(json.dumps(result, default=str).encode()),
                actual_credits=charge, execution_usage=execution_usage,
            )
        except Exception as exc:
            raise HTTPException(503, detail={
                "code": "settlement_unavailable", "message": "Execution ended, but credit settlement could not be confirmed. Check Runs before retrying.",
                "request_id": request_id,
            }) from exc
        finally:
            current_auth.reset(auth_token)
            reset_execution_meter(meter)
    response.headers["Cache-Control"] = "no-store"
    return {
        "ok": completed, "request_id": request_id,
        "result": {"status": result.get("status"), "data": result.get("data"),
                   "error": result.get("error"), "cleanup": (result.get("metadata") or {}).get("cleanup")},
        "usage": {"credits_reserved": reserved, "credits_charged": wallet_credits_for_raw(charge), "settled": True},
    }
