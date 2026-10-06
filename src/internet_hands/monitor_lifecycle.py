from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request

from .control_api import _json_error, _require_user, _require_verified
from .control_store import ControlError, ControlStore

router = APIRouter()
store = ControlStore()
MONITOR_TYPES = {"web", "api", "mcp", "gaming", "content", "product"}
EDITABLE_FIELDS = {"name", "type", "target", "interval_minutes", "config"}


def validate_monitor_spec(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    """Normalize and validate the user-editable monitor contract."""
    if not isinstance(payload, dict):
        raise ValueError("monitor input must be a JSON object")  # noqa: TRY004 -- shared validation contract
    normalized: dict[str, Any] = {}

    if not partial or "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("monitor name is required")
        normalized["name"] = name[:120]

    if not partial or "type" in payload:
        monitor_type = str(payload.get("type") or "web").strip().lower()
        if monitor_type not in MONITOR_TYPES:
            raise ValueError("monitor type must be web, api, mcp, gaming, content, or product")
        normalized["type"] = monitor_type
    else:
        monitor_type = None

    if not partial or "target" in payload:
        target = str(payload.get("target") or "").strip()
        if not target:
            raise ValueError("monitor target is required")
        if len(target) > 2000:
            raise ValueError("monitor target is too long")
        effective_type = monitor_type or str(payload.get("current_type") or "")
        if effective_type in {"web", "api", "mcp", "content", "product"}:
            parsed = urlparse(target)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"{effective_type} monitor target must be an http(s) URL")
        normalized["target"] = target

    if not partial or "interval_minutes" in payload:
        raw_interval = payload.get("interval_minutes")
        if raw_interval is None:
            raw_interval = 60
        try:
            interval = int(raw_interval)
        except (TypeError, ValueError) as exc:
            raise ValueError("interval_minutes must be an integer") from exc
        if not 5 <= interval <= 10080:
            raise ValueError("interval_minutes must be between 5 and 10080")
        normalized["interval_minutes"] = interval

    if "config" in payload or not partial:
        config = payload.get("config") or {}
        if not isinstance(config, dict):
            raise ValueError("config must be an object")
        normalized["config"] = config

    if (monitor_type or payload.get("current_type")) == "content" and (not partial or "config" in payload):
        key = normalized.get("config", {}).get("api_key_id")
        if not isinstance(key, str) or not key.strip() or len(key) > 120:
            raise ValueError("content monitors require an API key for billing")
        if set(normalized["config"]) != {"api_key_id"}:
            raise ValueError("content monitor config supports only api_key_id")
        normalized["config"] = {"api_key_id": key.strip()}

    if (monitor_type or payload.get("current_type")) == "product" and (not partial or "config" in payload):
        from .product_data import TRACK_FIELDS
        config = normalized.get("config", {})
        key = config.get("api_key_id")
        fields = config.get("fields")
        maximum = config.get("max_charge_credits")
        if not isinstance(key, str) or not key.strip() or len(key) > 120:
            raise ValueError("product monitors require an API key for billing")
        if not isinstance(fields, list) or not fields or any(not isinstance(f, str) or f not in TRACK_FIELDS for f in fields):
            raise ValueError("select price and/or availability to track")
        if type(maximum) is not int or not 0 <= maximum <= 1_000_000_000:
            raise ValueError("maximum check charge must be whole usage credits")
        if set(config) - {"api_key_id", "fields", "max_charge_credits", "preview_run_id"}:
            raise ValueError("unsupported product monitor config")
        normalized["config"] = {**config, "api_key_id": key.strip(), "fields": sorted(set(fields))}

    if partial and not normalized:
        raise ValueError("no editable monitor fields supplied")
    return normalized


def _monitor_or_404(user_id: str, monitor_id: str) -> dict[str, Any]:
    row = store.get_monitor(user_id, monitor_id)
    if not row:
        raise HTTPException(status_code=404, detail="monitor not found")
    return row


@router.post("/api/monitors/validate")
async def validate_monitor(request: Request):
    user = _require_verified(_require_user(request))
    body = await request.json()
    try:
        spec = validate_monitor_spec(body)
        if spec["type"] in {"content", "product"}:
            from .content_monitors import content_identity
            content_identity(store, user["id"], spec["config"])
        return {"valid": True, "monitor": spec}
    except ControlError as exc:
        raise _json_error(exc) from exc
    except ValueError as exc:
        detail = {"code": "invalid_monitor", "message": str(exc)}
        raise HTTPException(status_code=422, detail=detail) from exc


@router.patch("/api/monitors/{monitor_id}")
async def update_monitor(request: Request, monitor_id: str):
    user = _require_verified(_require_user(request))
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(422, detail="Expected a JSON object.")
    requested = {key: value for key, value in body.items() if key in EDITABLE_FIELDS}
    if not requested:
        detail = {"code": "invalid_monitor", "message": "no editable monitor fields supplied"}
        raise HTTPException(status_code=422, detail=detail)
    try:
        with store._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ih_monitors WHERE id=%s AND user_id=%s FOR UPDATE", (monitor_id, user["id"]))
            current = cur.fetchone()
            if not current:
                raise HTTPException(status_code=404, detail="monitor not found")
            merged = {key: requested.get(key, current.get(key)) for key in EDITABLE_FIELDS}
            validated = validate_monitor_spec(merged)
            if validated["type"] in {"content", "product"}:
                from .content_monitors import content_identity
                content_identity(store, user["id"], validated["config"])
            fields = {key: validated[key] for key in requested}
            reset_baseline = (current["type"] in {"content", "product"} or validated["type"] in {"content", "product"}) and any(
                current.get(key) != fields[key] for key in {"target", "type", "config"} & fields.keys())
            assignments: list[str] = []
            values: list[Any] = []
            for key in ("name", "type", "target", "interval_minutes"):
                if key in fields:
                    assignments.append(f"{key}=%s")
                    values.append(fields[key])
            if "config" in fields:
                assignments.append("config=%s::jsonb")
                values.append(json.dumps(fields["config"]))
            if "interval_minutes" in fields and not reset_baseline:
                assignments.append("next_check_at=now()+(%s || ' minutes')::interval")
                values.append(fields["interval_minutes"])
            if reset_baseline:
                assignments.extend(["content_version=content_version+1", "baseline_hash=NULL", "baseline_dataset_id=NULL",
                                    "last_status=NULL", "last_checked_at=NULL", "next_check_at=now()"])
            assignments.append("updated_at=now()")
            values.extend([monitor_id, user["id"]])
            cur.execute(
                f"UPDATE ih_monitors SET {', '.join(assignments)} "
                "WHERE id=%s AND user_id=%s RETURNING *",
                tuple(values),
            )
            row = cur.fetchone()
            conn.commit()
        if not row:
            raise HTTPException(status_code=404, detail="monitor not found")
        return dict(row)
    except ControlError as exc:
        raise _json_error(exc) from exc
    except ValueError as exc:
        detail = {"code": "invalid_monitor", "message": str(exc)}
        raise HTTPException(status_code=422, detail=detail) from exc


@router.get("/api/monitors/{monitor_id}/history")
def monitor_history(
    request: Request,
    monitor_id: str,
    limit: int = Query(50, ge=1, le=200),
    before: str | None = Query(default=None),
):
    user = _require_user(request)
    _monitor_or_404(user["id"], monitor_id)
    with store._connect() as conn, conn.cursor() as cur:
        if before:
            cur.execute(
                """
                SELECT * FROM ih_monitor_runs
                WHERE monitor_id=%s AND created_at < %s::timestamptz
                ORDER BY created_at DESC LIMIT %s
                """,
                (monitor_id, before, limit + 1),
            )
        else:
            cur.execute(
                "SELECT * FROM ih_monitor_runs "
                "WHERE monitor_id=%s ORDER BY created_at DESC LIMIT %s",
                (monitor_id, limit + 1),
            )
        rows = [dict(row) for row in cur.fetchall()]
    has_more = len(rows) > limit
    items = rows[:limit]
    next_before = items[-1]["created_at"].isoformat() if has_more and items else None
    return {"runs": items, "has_more": has_more, "next_before": next_before}
