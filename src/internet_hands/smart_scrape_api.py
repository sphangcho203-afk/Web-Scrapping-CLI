"""First-class Smart Scrape workflow over native HTTP and rendered semantic routes."""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

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

_TOOL = "mesh_capability_execute"
_CAPABILITIES = {
    "auto": "web.scrape.smart",
    "http": "web.scrape.http",
    "rendered": "web.scrape.rendered",
}
_ALLOWED_FORMATS = {"markdown", "html", "raw_html", "links", "screenshot"}
_RENDERED_FORMATS = {"html", "screenshot"}
_LINK_MD = re.compile(r"!?(?:\[([^\]]*)\])\([^)]*\)")
_MD_MARKERS = re.compile(r"(^|\s)[#>*_\x60~-]+(?=\s|$)")


def _json_body(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_input", "message": "Expected a JSON object."},
        )
    return value


async def _body(request: Request) -> dict[str, Any]:
    try:
        return _json_body(await request.json())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_json", "message": "Expected a JSON request body."},
        ) from exc


def _bounded_int(value: Any, name: str, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if type(value) is not int or not minimum <= value <= maximum:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_input",
                "message": f"{name} must be an integer from {minimum} to {maximum}.",
            },
        )
    return value


def _normalize_scrape(body: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    url = str(body.get("url") or "").strip()
    if not url:
        raise HTTPException(
            status_code=400,
            detail={"code": "url_required", "message": "Enter a public HTTP(S) URL."},
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

    mode = str(body.get("mode") or "auto").strip().lower()
    if mode not in _CAPABILITIES:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_input", "message": "mode must be auto, http, or rendered."},
        )

    requested = body.get("formats", ["markdown", "links"])
    if not isinstance(requested, list) or not requested or len(requested) > 5:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_input",
                "message": "formats must contain between 1 and 5 output formats.",
            },
        )
    formats: list[str] = []
    for item in requested:
        value = str(item).strip()
        if value not in _ALLOWED_FORMATS:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_input",
                    "message": f"Unsupported scrape format: {value or '(empty)'}.",
                },
            )
        if value not in formats:
            formats.append(value)

    only_main = body.get("only_main_content", True)
    mobile = body.get("mobile", False)
    if not isinstance(only_main, bool) or not isinstance(mobile, bool):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_input",
                "message": "only_main_content and mobile must be booleans.",
            },
        )
    timeout_ms = _bounded_int(body.get("timeout_ms"), "timeout_ms", 30_000, 1_000, 60_000)
    wait_ms = _bounded_int(body.get("wait_ms"), "wait_ms", 0, 0, 10_000)
    max_age_ms = _bounded_int(body.get("max_age_ms"), "max_age_ms", 0, 0, 86_400_000)
    max_bytes = _bounded_int(body.get("max_bytes"), "max_bytes", 2_000_000, 32_000, 8_000_000)

    requires_render = bool(
        set(formats) & _RENDERED_FORMATS or mobile or wait_ms > 0 or max_age_ms > 0
    )
    if mode == "http" and requires_render:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "render_required",
                "message": (
                    "Clean HTML, screenshots, mobile emulation, wait controls, and "
                    "provider cache controls require rendered mode."
                ),
            },
        )

    effective_mode = (
        "rendered"
        if mode == "rendered" or (mode == "auto" and requires_render)
        else mode
    )
    capability = _CAPABILITIES[effective_mode]

    provider_formats = ["rawHtml" if item == "raw_html" else item for item in formats]
    arguments: dict[str, Any] = {
        "url": url,
        "formats": provider_formats,
        "onlyMainContent": only_main,
        "timeout": timeout_ms,
        "maxBytes": max_bytes,
    }
    if effective_mode == "rendered":
        if wait_ms:
            arguments["waitFor"] = wait_ms
        if mobile:
            arguments["mobile"] = True
        if max_age_ms:
            arguments["maxAge"] = max_age_ms

    product = {
        "requested_mode": mode,
        "execution_mode": effective_mode,
        "formats": formats,
        "only_main_content": only_main,
        "timeout_ms": timeout_ms,
        "wait_ms": wait_ms,
        "mobile": mobile,
        "max_age_ms": max_age_ms,
        "max_bytes": max_bytes,
    }
    return capability, arguments, product


def _metered_arguments(
    body: dict[str, Any],
    capability: str,
    arguments: dict[str, Any],
    *,
    include_budget: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {"capability": capability, "arguments": arguments}
    if include_budget:
        for name in ("max_charge_credits", "quote_revision"):
            if name in body:
                result[name] = body[name]
    return result


def _plain_markdown(value: str) -> str:
    text = _LINK_MD.sub(lambda match: match.group(1) or "", value)
    text = _MD_MARKERS.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _links(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for item in value:
        raw = item.get("url") or item.get("href") if isinstance(item, dict) else item
        candidate = str(raw or "").strip()
        if not candidate.startswith(("http://", "https://")) or candidate in seen:
            continue
        seen.add(candidate)
        output.append(candidate)
        if len(output) >= 5000:
            break
    return output


def _safe_asset_url(value: Any) -> str | None:
    candidate = value.get("url") if isinstance(value, dict) else value
    candidate = str(candidate or "").strip()
    return candidate if candidate.startswith("https://") else None


def _normalize_document(data: Any, *, requested_url: str, route: str) -> dict[str, Any]:
    source = data if isinstance(data, dict) else {}
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    markdown = str(source.get("markdown") or "")
    text = str(source.get("text") or "") or _plain_markdown(markdown)
    raw_html = source.get("rawHtml")
    html = source.get("html")
    status = metadata.get("statusCode")
    try:
        status_code = int(status) if status is not None else None
    except (TypeError, ValueError):
        status_code = None

    return {
        "url": str(metadata.get("sourceURL") or source.get("url") or requested_url),
        "status_code": status_code,
        "content_type": metadata.get("contentType"),
        "title": metadata.get("title"),
        "description": metadata.get("description"),
        "text": text,
        "markdown": markdown or None,
        "html": str(html) if html is not None else None,
        "raw_html": str(raw_html) if raw_html is not None else None,
        "links": _links(source.get("links")),
        "screenshot": _safe_asset_url(source.get("screenshot")),
        "captured_at": metadata.get("capturedAt"),
        "sha256": metadata.get("sha256"),
        "execution_path": route,
    }


@router.post("/api/scrape/quote")
async def quote_scrape(request: Request):
    body = await _body(request)
    identity = _playground_identity(request, body)
    capability, arguments, product = _normalize_scrape(body)
    try:
        response = execution_quote(
            store,
            identity,
            _TOOL,
            _metered_arguments(body, capability, arguments, include_budget=False),
        )
        response["scrape"] = product | {"capability": capability}
        return response
    except ControlError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.detail},
        ) from exc


@router.post("/api/scrape/run")
async def run_scrape(request: Request):
    body = await _body(request)
    identity = _playground_identity(request, body)
    capability, arguments, product = _normalize_scrape(body)
    metered_arguments = _metered_arguments(body, capability, arguments, include_budget=True)
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
    try:
        routed = await get_capability_registry().execute(
            capability,
            arguments,
            wait_seconds=0,
            timeout_seconds=max(20, min(90, int(product["timeout_ms"] / 1000) + 15)),
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
            attempts = routed.get("attempts") or []
            last_error = next(
                (item.get("error") for item in reversed(attempts) if item.get("error")),
                routed.get("error"),
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "scrape_failed",
                    "message": last_error or "No scrape route completed successfully.",
                    "request_id": request_id,
                    "usage": {
                        "credits_reserved": reserved,
                        "credits_charged": charged,
                    },
                },
            )

        selected = str(routed.get("selected") or "")
        execution_path = "http" if selected.startswith("nativeweb:") else "rendered"
        document = _normalize_document(
            execution.get("data"),
            requested_url=arguments["url"],
            route=execution_path,
        )
        completed = True
        response: dict[str, Any] = {
            "ok": True,
            "request_id": request_id,
            "operation": "scrape",
            "usage": {
                "credits_reserved": reserved,
                "credits_charged": charged,
                "metered": True,
            },
            "summary": {
                "execution_path": execution_path,
                "status_code": document["status_code"],
                "formats": product["formats"],
                "text_bytes": len(document["text"].encode()),
                "links": len(document["links"]),
            },
            "result": document,
        }
        host = urlsplit(str(arguments["url"])).hostname or "page"
        saved = {
            "pages": [document],
            "source_url": arguments["url"],
            "execution_path": execution_path,
        }
        response.update(
            _save_output(
                identity.user_id,
                request_id,
                "scrape",
                saved,
                f"Scrape · {host}",
            )
        )
        output_bytes = len(
            json.dumps(response, default=str, separators=(",", ":")).encode()
        )
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
