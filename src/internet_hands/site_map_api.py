"""First-class, metered site-map workflow over the semantic capability registry."""
from __future__ import annotations

import json
import time
import uuid
from collections import Counter
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Request

from .auth import current_auth
from .capability_economics import settle_measured_cost
from .control_store import (
    ControlError,
    raw_credits_from_wallet_reservation,
    wallet_credits_for_raw,
)
from .execution_meter import execution_usage_snapshot, reset_execution_meter, start_execution_meter
from .playground_api import _playground_identity, _save_output, execution_quote, store
from .policy import PolicyError, ResolutionUnavailable, validate_public_http_url
from .tool_mcp import get_capability_registry

router = APIRouter()

_CAPABILITY = "web.map.site"
_TOOL = "mesh_capability_execute"
_CATEGORY_HINTS = (
    ("docs", ("docs", "documentation", "reference", "api", "developers", "developer")),
    ("pricing", ("pricing", "plans", "billing")),
    ("products", ("product", "products", "catalog", "shop", "store")),
    ("jobs", ("jobs", "careers", "career", "hiring")),
    ("news", ("news", "blog", "articles", "posts", "press")),
    ("company", ("about", "company", "contact", "team")),
    ("account", ("login", "signin", "sign-in", "signup", "sign-up", "auth", "account")),
)


def _json_body(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_input", "message": "Expected a JSON object."},
        )
    return value


def _map_arguments(body: dict[str, Any]) -> dict[str, Any]:
    url = str(body.get("url") or "").strip()
    if not url:
        raise HTTPException(
            status_code=400,
            detail={"code": "url_required", "message": "Enter a public HTTP(S) site root."},
        )
    try:
        validate_public_http_url(url)
    except ResolutionUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "resolver_busy", "message": str(exc)},
            headers={"Retry-After": "1"},
        ) from exc
    except PolicyError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "target_blocked", "message": str(exc)},
        ) from exc

    raw_limit = body.get("limit", 250)
    if type(raw_limit) is not int or not 1 <= raw_limit <= 1000:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_input", "message": "limit must be an integer from 1 to 1000."},
        )
    search = str(body.get("search") or "").strip()
    if len(search) > 160:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_input", "message": "search must be at most 160 characters."},
        )
    include_subdomains = body.get("include_subdomains", False)
    if not isinstance(include_subdomains, bool):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_input", "message": "include_subdomains must be a boolean."},
        )
    sitemap_mode = str(body.get("sitemap_mode") or "auto").strip().lower()
    if sitemap_mode not in {"auto", "only", "ignore"}:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_input", "message": "sitemap_mode must be auto, only, or ignore."},
        )

    arguments: dict[str, Any] = {
        "url": url,
        "limit": raw_limit,
        "includeSubdomains": include_subdomains,
    }
    if search:
        arguments["search"] = search
    if sitemap_mode == "only":
        arguments["sitemapOnly"] = True
    elif sitemap_mode == "ignore":
        arguments["ignoreSitemap"] = True
    return arguments


def _metered_arguments(body: dict[str, Any], arguments: dict[str, Any], *, include_budget: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"capability": _CAPABILITY, "arguments": arguments}
    if include_budget:
        for name in ("max_charge_credits", "quote_revision"):
            if name in body:
                result[name] = body[name]
    return result


def _canonical_url(value: str) -> str | None:
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def _host_allowed(candidate: str, root: str, include_subdomains: bool) -> bool:
    candidate_host = (urlsplit(candidate).hostname or "").rstrip(".").casefold()
    root_host = (urlsplit(root).hostname or "").rstrip(".").casefold()
    canonical = root_host.removeprefix("www.")
    if candidate_host in {root_host, canonical, "www." + canonical}:
        return True
    return bool(include_subdomains and canonical and candidate_host.endswith("." + canonical))


def _category(path: str) -> str:
    segments = [part.casefold() for part in path.split("/") if part]
    if not segments:
        return "home"
    searchable = " ".join(segments)
    for category, hints in _CATEGORY_HINTS:
        if any(hint in searchable for hint in hints):
            return category
    return "other"


def _parent_url(url: str) -> str | None:
    parts = urlsplit(url)
    segments = [part for part in parts.path.split("/") if part]
    if not segments:
        return None
    parent_path = "/" if len(segments) == 1 else "/" + "/".join(segments[:-1]) + "/"
    return urlunsplit((parts.scheme, parts.netloc, parent_path, "", ""))


def _normalized_rows(data: Any, *, root_url: str, limit: int, include_subdomains: bool) -> tuple[list[dict[str, Any]], int, bool]:
    if isinstance(data, list):
        raw_items = data
        provider_total = len(data)
        provider_truncated = False
    elif isinstance(data, dict):
        raw_items = data.get("links") or data.get("urls") or data.get("results") or []
        if isinstance(raw_items, dict):
            raw_items = raw_items.get("links") or raw_items.get("urls") or []
        provider_total = int(data.get("total_links") or data.get("total") or len(raw_items or []))
        provider_truncated = bool(data.get("truncated"))
    else:
        raw_items, provider_total, provider_truncated = [], 0, False

    if not isinstance(raw_items, list):
        raw_items = []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_items:
        title = None
        description = None
        if isinstance(item, str):
            candidate = item
        elif isinstance(item, dict):
            candidate = str(item.get("url") or item.get("link") or item.get("href") or "")
            title = item.get("title")
            description = item.get("description") or item.get("snippet")
        else:
            continue
        normalized = _canonical_url(candidate)
        if not normalized or normalized in seen or not _host_allowed(normalized, root_url, include_subdomains):
            continue
        seen.add(normalized)
        parts = urlsplit(normalized)
        segments = [part for part in parts.path.split("/") if part]
        rows.append(
            {
                "url": normalized,
                "title": str(title)[:500] if title else None,
                "description": str(description)[:1200] if description else None,
                "path": parts.path or "/",
                "depth": len(segments),
                "category": _category(parts.path or "/"),
                "parent_url": _parent_url(normalized),
            }
        )
        if len(rows) >= limit:
            break
    return rows, max(provider_total, len(rows)), provider_truncated or provider_total > len(rows)


def _result_payload(execution_data: Any, *, arguments: dict[str, Any]) -> dict[str, Any]:
    rows, reported_total, truncated = _normalized_rows(
        execution_data,
        root_url=str(arguments["url"]),
        limit=int(arguments["limit"]),
        include_subdomains=bool(arguments.get("includeSubdomains")),
    )
    categories = Counter(str(row["category"]) for row in rows)
    max_depth = max((int(row["depth"]) for row in rows), default=0)
    return {
        "root_url": arguments["url"],
        "search": arguments.get("search"),
        "include_subdomains": bool(arguments.get("includeSubdomains")),
        "sitemap_mode": "only" if arguments.get("sitemapOnly") else "ignore" if arguments.get("ignoreSitemap") else "auto",
        "urls": rows,
        "returned_urls": len(rows),
        "reported_urls": reported_total,
        "truncated": truncated,
        "max_depth": max_depth,
        "categories": dict(sorted(categories.items())),
    }


async def _body(request: Request) -> dict[str, Any]:
    try:
        return _json_body(await request.json())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_json", "message": "Expected a JSON request body."},
        ) from exc


@router.post("/api/site-map/quote")
async def quote_site_map(request: Request):
    body = await _body(request)
    identity = _playground_identity(request, body)
    arguments = _map_arguments(body)
    try:
        return execution_quote(
            store,
            identity,
            _TOOL,
            _metered_arguments(body, arguments, include_budget=False),
        )
    except ControlError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.detail},
        ) from exc


@router.post("/api/site-map/run")
async def run_site_map(request: Request):
    body = await _body(request)
    identity = _playground_identity(request, body)
    arguments = _map_arguments(body)
    metered_arguments = _metered_arguments(body, arguments, include_budget=True)
    request_id = "req_" + uuid.uuid4().hex
    try:
        reserved = store.reserve_tool_call(
            identity=identity,
            request_id=request_id,
            tool_name=_TOOL,
            arguments=metered_arguments,
            input_bytes=len(json.dumps(body, separators=(",", ":")).encode()),
        )
        raw_reserved = raw_credits_from_wallet_reservation(reserved)
    except ControlError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.detail},
        ) from exc

    meter = start_execution_meter()
    auth_token = current_auth.set(identity)
    started = time.monotonic()
    completed = False
    output_bytes = 0
    response: dict[str, Any] | None = None
    try:
        routed = await get_capability_registry().execute(
            _CAPABILITY,
            arguments,
            wait_seconds=0,
            timeout_seconds=35,
        )
        execution = routed.get("execution") or {}
        usage_snapshot = execution_usage_snapshot()
        raw_charge = settle_measured_cost(
            _TOOL,
            metered_arguments,
            identity.plan_slug,
            reserved_credits=raw_reserved,
            execution_usage=usage_snapshot,
        )
        charged = wallet_credits_for_raw(raw_charge)
        if execution.get("status") not in {"completed", "ok"}:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "site_map_failed",
                    "message": execution.get("error") or routed.get("error") or "No site-map route completed successfully.",
                    "request_id": request_id,
                    "usage": {"credits_reserved": reserved, "credits_charged": charged},
                },
            )

        payload = _result_payload(execution.get("data"), arguments=arguments)
        completed = True
        response = {
            "ok": True,
            "request_id": request_id,
            "operation": "map",
            "usage": {
                "credits_reserved": reserved,
                "credits_charged": charged,
                "metered": True,
            },
            "summary": {
                "returned_urls": payload["returned_urls"],
                "reported_urls": payload["reported_urls"],
                "max_depth": payload["max_depth"],
                "truncated": payload["truncated"],
                "categories": payload["categories"],
            },
            "result": payload,
        }
        host = urlsplit(str(arguments["url"])).hostname or "site"
        response.update(_save_output(identity.user_id, request_id, "map", payload, f"Site map · {host}"))
        output_bytes = len(json.dumps(response, default=str, separators=(",", ":")).encode())
        return response
    finally:
        elapsed = max(0, int((time.monotonic() - started) * 1000))
        usage = {**execution_usage_snapshot(), "completed": completed}
        try:
            store.finish_usage(
                request_id,
                status="ok" if completed else "error",
                latency_ms=elapsed,
                output_bytes=output_bytes,
                actual_credits=settle_measured_cost(
                    _TOOL,
                    metered_arguments,
                    identity.plan_slug,
                    reserved_credits=raw_reserved,
                    execution_usage=usage,
                    latency_ms=elapsed,
                ),
                execution_usage=usage,
            )
        finally:
            current_auth.reset(auth_token)
            reset_execution_meter(meter)
