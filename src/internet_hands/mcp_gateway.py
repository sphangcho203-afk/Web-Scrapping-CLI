from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any

from starlette.responses import JSONResponse

from .auth import authenticate_secret, current_auth
from .capability_economics import settle_measured_cost
from .control_store import (
    AuthIdentity,
    ControlError,
    ControlStore,
    raw_credits_from_wallet_reservation,
)
from .execution_meter import (
    execution_usage_snapshot,
    reset_execution_meter,
    start_execution_meter,
)

logger = logging.getLogger(__name__)
_MAX_RESULT_INSPECTION_BYTES = 2_000_000


def _tool_outcome(body: bytes) -> tuple[str | None, bool | None]:
    """Inspect MCP results without treating HTTP 200 as command success."""
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None, None
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        return None, None
    if "error" in payload:
        return "error", False
    result = payload.get("result")
    if not isinstance(result, dict):
        return None, None
    if result.get("isError") is True:
        return "error", False
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        status = structured.get("status")
        if not isinstance(status, str):
            status = None
        if status in {"cancelled", "canceled"}:
            return "cancelled", False
        if status in {"failed", "error", "timed_out", "timeout"} or structured.get("error"):
            return "error", False
        if status in {"queued", "running", "waiting", "accepted", "dry_run"}:
            return "ok", False
    return "ok", True


async def preflight_semantic_call(tool_name: str, arguments: dict[str, Any] | None) -> None:
    """Check semantic setup under the caller's identity before reserving any credits."""
    if tool_name not in {"mesh_capability_execute", "gaming_intel"}:
        return
    from .tool_mcp import get_capability_registry

    args = arguments or {}
    registry = get_capability_registry()
    requests = args.get("requests") if tool_name == "gaming_intel" else [args]
    if not isinstance(requests, list) or len(requests) > 20:
        raise ControlError("invalid_arguments", "Supply at most 20 capability requests.", 422)
    semaphore = asyncio.Semaphore(5)

    async def inspect(item: Any) -> None:
        if not isinstance(item, dict) or not isinstance(item.get("arguments", {}), dict):
            raise ControlError("invalid_arguments", "Each capability request needs an arguments object.", 422)
        capability_id = item.get("capability")
        if not isinstance(capability_id, str) or capability_id not in registry.capabilities:
            raise ControlError("capability_not_found", "This capability is not registered.", 404)
        capability = registry.capabilities[capability_id]
        if tool_name == "gaming_intel" and (
            not capability.read_only or ("gaming" not in capability.tags and capability.pack != "mlbb")
        ):
            raise ControlError("invalid_arguments", "Gaming requests must use read-only gaming capabilities.", 422)
        async with semaphore:
            await registry.preflight(
                capability_id, item.get("arguments", {}),
                provider_preference=item.get("provider_preference"),
                allow_side_effects=item.get("allow_side_effects") is True,
                dry_run=args.get("dry_run") is True,
            )

    tasks = [asyncio.create_task(inspect(item)) for item in requests]
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=10.0)
    except TimeoutError as exc:
        raise ControlError("capability_unavailable", "The availability check timed out. Try again before running this operation.", 409) from exc
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class MCPGatewayASGI:
    """Authenticate, rate-limit, and meter Streamable HTTP MCP calls."""

    def __init__(self, app: Any, store: ControlStore | None = None) -> None:
        self.app = app
        self.store = store or ControlStore()

    async def _read_body(self, receive: Any, max_bytes: int = 2_000_000) -> bytes:
        chunks: list[bytes] = []
        total = 0
        more = True
        while more:
            message = await receive()
            if message.get("type") == "http.disconnect":
                raise ControlError("request_disconnected", "MCP request disconnected before its body completed", 400)
            if message.get("type") != "http.request":
                continue
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > max_bytes:
                raise ControlError("request_too_large", "MCP request exceeds 2 MB", 413)
            chunks.append(chunk)
            more = bool(message.get("more_body"))
        return b"".join(chunks)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        host = headers.get("host", "")
        scheme = headers.get("x-forwarded-proto") or scope.get("scheme", "https")
        metadata_url = (
            f"{scheme}://{host}/.well-known/oauth-protected-resource"
            if host
            else "/.well-known/oauth-protected-resource"
        )

        supplied = headers.get("x-api-key")
        authorization = headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()

        master_key = os.getenv("INTERNET_HANDS_API_KEY")
        identity: AuthIdentity | None = None
        master = bool(supplied and master_key and secrets_equal(supplied, master_key))
        if supplied and not master:
            try:
                identity = await asyncio.to_thread(authenticate_secret, self.store, supplied)
            except ControlError as exc:
                response = JSONResponse(
                    {"error": exc.code, "detail": exc.detail}, status_code=exc.status_code
                )
                await response(scope, receive, send)
                return

        if not master and not identity:
            response = JSONResponse(
                {"error": "invalid_api_key", "detail": "authentication required"},
                status_code=401,
                headers={
                    "WWW-Authenticate": f'Bearer resource_metadata="{metadata_url}"',
                    "Cache-Control": "no-store",
                },
            )
            await response(scope, receive, send)
            return

        # The hosted transport is stateless and responds to POSTs with JSON.
        # A standalone SSE stream has no useful backchannel and exceeds the
        # serverless request lifetime. MCP clients must accept 405 here.
        if scope.get("method", "GET").upper() == "GET":
            response = JSONResponse(
                {"detail": "Use POST for this stateless Streamable HTTP MCP endpoint"},
                status_code=405,
                headers={"Allow": "POST", "Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return

        body = b""
        try:
            if scope.get("method", "GET").upper() in {"POST", "PUT", "PATCH"}:
                body = await self._read_body(receive)
        except ControlError as exc:
            response = JSONResponse(
                {"error": exc.code, "detail": exc.detail}, status_code=exc.status_code
            )
            await response(scope, receive, send)
            return

        replayed = False

        async def replay_receive() -> dict[str, Any]:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        request_id = f"req_{uuid.uuid4().hex}"
        tool_name: str | None = None
        arguments: dict[str, Any] | None = None
        if body:
            try:
                payload = json.loads(body)
                if isinstance(payload, dict) and payload.get("method") == "tools/call":
                    params = payload.get("params") or {}
                    if isinstance(params, dict):
                        tool_name = str(params.get("name") or "") or None
                        args = params.get("arguments")
                        if isinstance(args, dict):
                            arguments = args
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        started = time.monotonic()
        token = None
        meter_token = None
        credits_reserved: int | None = None
        if identity:
            token = current_auth.set(identity)
            if tool_name:
                try:
                    await preflight_semantic_call(tool_name, arguments)
                    credits_reserved = self.store.reserve_tool_call(
                        identity=identity,
                        request_id=request_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        input_bytes=len(body),
                    )
                    meter_token = start_execution_meter()
                except ControlError as exc:
                    current_auth.reset(token)
                    response = JSONResponse(
                        {"error": exc.code, "detail": exc.detail, "request_id": request_id},
                        status_code=exc.status_code,
                        headers={"X-Request-ID": request_id},
                    )
                    await response(scope, replay_receive, send)
                    return
                except BaseException:
                    current_auth.reset(token)
                    raise

        status_code = 200
        output_bytes = 0
        result_body = bytearray()
        result_complete = False
        result_overflow = False

        async def metered_send(message: dict[str, Any]) -> None:
            nonlocal status_code, output_bytes, result_complete, result_overflow
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 200))
                headers_out = list(message.get("headers") or [])
                headers_out.append((b"x-request-id", request_id.encode()))
                if credits_reserved is not None:
                    headers_out.append(
                        (b"x-credits-reserved", str(credits_reserved).encode())
                    )
                message = dict(message)
                message["headers"] = headers_out
            elif message.get("type") == "http.response.body":
                chunk = message.get("body", b"")
                output_bytes += len(chunk)
                if identity and tool_name and not result_overflow:
                    if len(result_body) + len(chunk) <= _MAX_RESULT_INSPECTION_BYTES:
                        result_body.extend(chunk)
                    else:
                        result_body.clear()
                        result_overflow = True
                result_complete = not message.get("more_body", False)
            await send(message)

        terminal_status = "ok"
        try:
            await self.app(scope, replay_receive if body else receive, metered_send)
        except asyncio.CancelledError:
            terminal_status = "cancelled"
            raise
        except Exception:
            terminal_status = "error"
            raise
        finally:
            completed = None
            if terminal_status == "ok" and result_complete and not result_overflow:
                outcome, completed = _tool_outcome(bytes(result_body))
                if outcome is not None:
                    terminal_status = outcome
            if status_code >= 400 and terminal_status == "ok":
                terminal_status = "error"
            if terminal_status != "ok":
                completed = False
            if identity and tool_name:
                elapsed = int((time.monotonic() - started) * 1000)
                usage = execution_usage_snapshot() if meter_token is not None else {}
                if usage:
                    usage["elapsed_ms"] = elapsed
                if completed is not None:
                    usage["completed"] = completed

                actual_credits: int | None = None
                if credits_reserved is not None:
                    try:
                        actual_credits = settle_measured_cost(
                            tool_name,
                            arguments,
                            identity.plan_slug,
                            reserved_credits=raw_credits_from_wallet_reservation(credits_reserved),
                            execution_usage=usage,
                            latency_ms=elapsed,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "measured pricing failed for request %s; using reservation: %s",
                            request_id,
                            exc,
                        )

                try:
                    self.store.finish_usage(
                        request_id,
                        status=terminal_status,
                        latency_ms=elapsed,
                        output_bytes=output_bytes,
                        actual_credits=actual_credits,
                        execution_usage=usage or None,
                    )
                except Exception as exc:  # noqa: BLE001
                    # Metering must never corrupt the already-produced MCP protocol response.
                    logger.warning(
                        "usage metering finalization failed for request %s: %s",
                        request_id,
                        exc,
                    )

            if meter_token is not None:
                reset_execution_meter(meter_token)
            if token is not None:
                current_auth.reset(token)


def secrets_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode(), right.encode())
