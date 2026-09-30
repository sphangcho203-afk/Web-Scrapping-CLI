from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from .auth import authenticate_secret
from .control_api import _require_user, store
from .control_store import ControlError
from .datasets import DatasetStore, export_rows
from .playground_api import _request_credential

router = APIRouter()
datasets = DatasetStore(store)


def _owner(request: Request, *, write: bool = False) -> str:
    secret = _request_credential(request)
    if not secret:
        return _require_user(request)["id"]
    try:
        identity = authenticate_secret(store, secret)
    except ControlError as exc:
        raise _error(exc) from exc
    if not identity:
        raise HTTPException(401, detail={"code": "invalid_api_key", "message": "A valid API key is required."})
    scope = "mcp:execute" if write else "mcp:read"
    if "*" not in identity.scopes and scope not in identity.scopes:
        raise HTTPException(403, detail={"code": "scope_required", "message": f"This operation requires {scope}."})
    return identity.user_id


def _error(exc: ControlError) -> HTTPException:
    return HTTPException(exc.status_code, detail={"code": exc.code, "message": exc.detail})


@router.get("/api/datasets")
def list_datasets(request: Request, limit: int = Query(25, ge=1, le=100),
                  offset: int = Query(0, ge=0, le=100000)):
    user_id = _owner(request)
    try:
        return datasets.list(user_id, limit=limit, offset=offset)
    except ControlError as exc:
        raise _error(exc) from exc


@router.get("/api/datasets/{dataset_id}")
def dataset_detail(request: Request, dataset_id: str, limit: int = Query(50, ge=1, le=100),
                   offset: int = Query(0, ge=0, le=100000), q: str = Query("", max_length=200)):
    user_id = _owner(request)
    try:
        row = datasets.get(user_id, dataset_id)
    except ControlError as exc:
        raise _error(exc) from exc
    rows = row.pop("rows")
    row.pop("output", None)
    row.pop("user_id", None)
    if q:
        rows = [item for item in rows if q.casefold() in json.dumps(item, ensure_ascii=False).casefold()]
    return {"dataset": row, "rows": rows[offset:offset + limit], "total": len(rows),
            "limit": limit, "offset": offset}


@router.get("/api/datasets/{dataset_id}/export")
def dataset_export(request: Request, dataset_id: str, format: str = Query("json", pattern="^(json|jsonl|csv)$")):
    user_id = _owner(request)
    try:
        row = datasets.get(user_id, dataset_id)
    except ControlError as exc:
        raise _error(exc) from exc
    content, media_type = export_rows(row["rows"], format)
    # Never put user-controlled names into HTTP headers.
    safe_id = "".join(c for c in row["id"] if c.isalnum() or c == "_")
    return Response(content, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{safe_id}.{format}"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


@router.patch("/api/datasets/{dataset_id}")
async def rename_dataset(request: Request, dataset_id: str):
    user_id = _owner(request, write=True)
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, detail={"code": "invalid_json", "message": "Expected a JSON object."}) from exc
    name = body.get("name") if isinstance(body, dict) else None
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        raise HTTPException(422, detail={"code": "invalid_name", "message": "Name must contain 1–120 characters."})
    try:
        return {"dataset": datasets.rename(user_id, dataset_id, name.strip())}
    except ControlError as exc:
        raise _error(exc) from exc


@router.delete("/api/datasets/{dataset_id}")
def delete_dataset(request: Request, dataset_id: str):
    user_id = _owner(request, write=True)
    try:
        datasets.delete(user_id, dataset_id)
    except ControlError as exc:
        raise _error(exc) from exc
    return {"deleted": True}
