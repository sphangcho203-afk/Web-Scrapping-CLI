from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .control_api import _require_user
from .control_store import AuthIdentity, ControlError, ControlStore
from .crawler import crawl
from .policy import PolicyError, ResolutionUnavailable, validate_public_http_url

router = APIRouter()
store = ControlStore()

_SAFE_EXCLUDES = (
    "*/logout*",
    "*/signout*",
    "*/sign-out*",
    "*/delete*",
    "*/unsubscribe*",
    "*/checkout*",
)


def _http_error(exc: ControlError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.detail})


def _playground_identity(request: Request, body: dict[str, Any]) -> AuthIdentity:
    user = _require_user(request)
    key_id = str(body.get("api_key_id") or "").strip()
    if not key_id:
        raise HTTPException(
            status_code=409,
            detail={"code": "api_key_required", "message": "Create an API key in the API Keys section before using Playground."},
        )
    try:
        identity = store.api_key_identity_for_user(user["id"], key_id)
    except ControlError as exc:
        raise _http_error(exc) from exc
    if not identity:
        raise HTTPException(
            status_code=409,
            detail={"code": "api_key_required", "message": "That API key is unavailable or revoked. Create or select an active key."},
        )
    scopes = set(identity.scopes or [])
    if "*" not in scopes and "mcp:execute" not in scopes:
        raise HTTPException(
            status_code=403,
            detail={"code": "scope_required", "message": "This API key needs the mcp:execute scope."},
        )
    return identity


def _bounded_int(value: Any, name: str, default: int, minimum: int, maximum: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_input", "message": f"{name} must be an integer"}) from exc
    if parsed < minimum or parsed > maximum:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_input", "message": f"{name} must be between {minimum} and {maximum}"},
        )
    return parsed


def _patterns(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise HTTPException(status_code=400, detail={"code": "invalid_input", "message": f"{name} must be a string array"})
    cleaned = [item.strip() for item in value if item.strip()]
    if len(cleaned) > 20 or any(len(item) > 200 for item in cleaned):
        raise HTTPException(status_code=400, detail={"code": "invalid_input", "message": f"{name} is too large"})
    return cleaned


@router.post("/api/playground/run")
async def playground_run(request: Request):
    raw = await request.body()
    try:
        body = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_json", "message": "Request body must be valid JSON."}) from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail={"code": "invalid_input", "message": "Request body must be a JSON object."})

    identity = _playground_identity(request, body)
    operation = str(body.get("operation") or "crawl").strip().lower()
    if operation != "crawl":
        raise HTTPException(status_code=400, detail={"code": "unsupported_operation", "message": "The current playground supports the crawl operation."})

    url = str(body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail={"code": "url_required", "message": "Enter a public HTTP(S) URL to crawl."})
    try:
        validate_public_http_url(url)
    except ResolutionUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "resolver_busy", "message": str(exc)},
            headers={"Retry-After": "1"},
        ) from exc
    except PolicyError as exc:
        raise HTTPException(status_code=400, detail={"code": "target_blocked", "message": str(exc)}) from exc

    max_pages = _bounded_int(body.get("max_pages"), "max_pages", 12, 1, 50)
    max_depth = _bounded_int(body.get("max_depth"), "max_depth", 2, 0, 4)
    concurrency = _bounded_int(body.get("concurrency"), "concurrency", 4, 1, 6)
    max_seconds = _bounded_int(body.get("max_seconds"), "max_seconds", 30, 5, 45)
    include_paths = _patterns(body.get("include_paths"), "include_paths")
    exclude_paths = [*_SAFE_EXCLUDES, *_patterns(body.get("exclude_paths"), "exclude_paths")]
    include_subdomains = bool(body.get("include_subdomains", False))
    preserve_query = bool(body.get("preserve_query", False))

    request_id = f"req_{uuid.uuid4().hex}"
    arguments = {
        "ref": "playground:crawl",
        "url": url,
        "max_pages": max_pages,
        "max_depth": max_depth,
        "concurrency": concurrency,
        "max_seconds": max_seconds,
        "include_subdomains": include_subdomains,
        "preserve_query": preserve_query,
    }
    try:
        credits = store.charge_tool_call(
            identity=identity,
            request_id=request_id,
            tool_name="playground:crawl",
            arguments=arguments,
            input_bytes=len(raw),
        )
    except ControlError as exc:
        raise _http_error(exc) from exc

    started = time.monotonic()
    status = "error"
    output_bytes = 0
    try:
        result = await crawl(
            url,
            max_pages=max_pages,
            max_depth=max_depth,
            concurrency=concurrency,
            max_seconds=float(max_seconds),
            delay_seconds=0.10,
            respect_robots=True,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            include_subdomains=include_subdomains,
            preserve_query=preserve_query,
            max_bytes_per_page=2_000_000,
        )
        payload = result.model_dump(mode="json")
        pages = payload.get("pages") or []
        summary = {
            "pages": len(pages),
            "successful": sum(1 for page in pages if page.get("status_code") and not page.get("error")),
            "failed": sum(1 for page in pages if page.get("error")),
            "links_found": sum(int(page.get("links_found") or 0) for page in pages),
            "discovered_urls": int(payload.get("discovered_urls") or 0),
            "skipped_urls": int(payload.get("skipped_urls") or 0),
            "duration_ms": int(payload.get("duration_ms") or 0),
            "truncated": bool(payload.get("truncated")),
        }
        response = {
            "ok": True,
            "request_id": request_id,
            "operation": operation,
            "usage": {"credits_charged": credits, "metered": True},
            "summary": summary,
            "result": payload,
        }
        output_bytes = len(json.dumps(response, default=str, separators=(",", ":")).encode())
        status = "ok"
        return response
    except ResolutionUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "resolver_busy", "message": str(exc), "request_id": request_id, "credits_charged": credits},
            headers={"Retry-After": "1"},
        ) from exc
    except (ValueError, PolicyError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "crawl_rejected", "message": str(exc), "request_id": request_id, "credits_charged": credits},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "crawl_failed", "message": f"{type(exc).__name__}: {exc}", "request_id": request_id, "credits_charged": credits},
        ) from exc
    finally:
        elapsed = max(0, int((time.monotonic() - started) * 1000))
        try:
            store.finish_usage(request_id, status=status, latency_ms=elapsed, output_bytes=output_bytes)
        except Exception:
            pass
