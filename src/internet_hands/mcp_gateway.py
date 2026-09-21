from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any

from starlette.responses import JSONResponse

from .auth import authenticate_secret, current_auth
from .control_store import AuthIdentity, ControlError, ControlStore

logger = logging.getLogger(__name__)


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
                identity = authenticate_secret(self.store, supplied)
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

        async def replay_receive() -> dict[str, Any]:
            nonlocal body
            payload = body
            body = b""
            return {"type": "http.request", "body": payload, "more_body": False}

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
        credits_charged: int | None = None
        if identity:
            token = current_auth.set(identity)
            if tool_name:
                try:
                    credits_charged = self.store.charge_tool_call(
                        identity=identity,
                        request_id=request_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        input_bytes=len(body),
                    )
                except ControlError as exc:
                    current_auth.reset(token)
                    response = JSONResponse(
                        {"error": exc.code, "detail": exc.detail, "request_id": request_id},
                        status_code=exc.status_code,
                        headers={"X-Request-ID": request_id},
                    )
                    await response(scope, replay_receive, send)
                    return

        status_code = 200
        output_bytes = 0

        async def metered_send(message: dict[str, Any]) -> None:
            nonlocal status_code, output_bytes
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 200))
                headers_out = list(message.get("headers") or [])
                headers_out.append((b"x-request-id", request_id.encode()))
                if credits_charged is not None:
                    headers_out.append(
                        (b"x-credits-charged", str(credits_charged).encode())
                    )
                message = dict(message)
                message["headers"] = headers_out
            elif message.get("type") == "http.response.body":
                output_bytes += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, replay_receive if body else receive, metered_send)
        finally:
            if identity and tool_name:
                elapsed = int((time.monotonic() - started) * 1000)
                try:
                    self.store.finish_usage(
                        request_id,
                        status="ok" if status_code < 400 else "error",
                        latency_ms=elapsed,
                        output_bytes=output_bytes,
                    )
                except Exception as exc:  # noqa: BLE001
                    # Metering must never corrupt the already-produced MCP protocol response.
                    logger.warning(
                        "usage metering finalization failed for request %s: %s",
                        request_id,
                        exc,
                    )
            if token is not None:
                current_auth.reset(token)


def secrets_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode(), right.encode())
