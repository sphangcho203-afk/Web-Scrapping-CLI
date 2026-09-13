from __future__ import annotations

from typing import Any

import pytest
from starlette.responses import JSONResponse

from internet_hands.control_store import AuthIdentity
from internet_hands.mcp_gateway import MCPGatewayASGI


async def _inner_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    response = JSONResponse({"ok": True})
    await response(scope, receive, send)


async def _request(app: Any, *, headers: list[tuple[bytes, bytes]], body: bytes = b"") -> tuple[int, dict[str, str], bytes]:
    messages = [
        {"type": "http.request", "body": body, "more_body": False},
    ]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "scheme": "https",
        "path": "/mcp",
        "headers": headers,
    }
    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    chunks = [m.get("body", b"") for m in sent if m["type"] == "http.response.body"]
    return (
        int(start["status"]),
        {k.decode().lower(): v.decode() for k, v in start.get("headers", [])},
        b"".join(chunks),
    )


@pytest.mark.asyncio
async def test_unauthenticated_mcp_returns_oauth_resource_metadata() -> None:
    app = MCPGatewayASGI(_inner_app)
    status, headers, body = await _request(
        app,
        headers=[(b"host", b"mcp.example.test")],
        body=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
    )
    assert status == 401
    assert "resource_metadata=\"https://mcp.example.test/.well-known/oauth-protected-resource\"" in headers[
        "www-authenticate"
    ]
    assert b"authentication required" in body


class _FakeStore:
    def __init__(self) -> None:
        self.charged: list[dict[str, Any]] = []
        self.finished: list[dict[str, Any]] = []

    def charge_tool_call(self, **kwargs: Any) -> int:
        self.charged.append(kwargs)
        return 3

    def finish_usage(self, request_id: str, **kwargs: Any) -> None:
        self.finished.append({"request_id": request_id, **kwargs})


@pytest.mark.asyncio
async def test_customer_tool_call_is_metered(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = AuthIdentity(
        user_id="usr_1",
        api_key_id="key_1",
        scopes=["mcp:read", "mcp:execute"],
        plan_slug="pro",
        rpm_limit=240,
        source="api_key",
    )
    store = _FakeStore()
    monkeypatch.setattr("internet_hands.mcp_gateway.authenticate_secret", lambda _store, _secret: identity)
    app = MCPGatewayASGI(_inner_app, store=store)  # type: ignore[arg-type]
    body = b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"gaming_profile","arguments":{"game":"mlbb"}}}'
    status, headers, response_body = await _request(
        app,
        headers=[(b"host", b"mcp.example.test"), (b"authorization", b"Bearer ih_live_fake")],
        body=body,
    )
    assert status == 200
    assert response_body == b'{"ok":true}'
    assert headers["x-request-id"].startswith("req_")
    assert len(store.charged) == 1
    assert store.charged[0]["tool_name"] == "gaming_profile"
    assert store.charged[0]["arguments"] == {"game": "mlbb"}
    assert len(store.finished) == 1
    assert store.finished[0]["status"] == "ok"
