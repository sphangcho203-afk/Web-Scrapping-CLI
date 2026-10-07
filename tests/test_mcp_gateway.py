from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from starlette.responses import JSONResponse

from internet_hands.control_store import AuthIdentity
from internet_hands.execution_meter import record_provider_call, record_usage
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
    def __init__(self, reserved: int = 3) -> None:
        self.reserved = reserved
        self.charged: list[dict[str, Any]] = []
        self.finished: list[dict[str, Any]] = []

    def reserve_tool_call(self, **kwargs: Any) -> int:
        self.charged.append(kwargs)
        return self.reserved

    def finish_usage(self, request_id: str, **kwargs: Any) -> None:
        self.finished.append({"request_id": request_id, **kwargs})


@pytest.mark.asyncio
@pytest.mark.parametrize("result,expected", [
    ({"error": {"code": -32602, "message": "Invalid params"}}, "error"),
    ({"result": {"isError": True, "content": []}}, "error"),
    ({"result": {"structuredContent": {"status": "failed"}}}, "error"),
    ({"result": {"structuredContent": {"status": "cancelled"}}}, "cancelled"),
    ({"result": {"structuredContent": {"status": ["unexpected"]}}}, "ok"),
])
async def test_chunked_mcp_result_is_forwarded_unchanged_and_settled_once(monkeypatch, result, expected):
    from internet_hands.auth import current_auth

    body = json.dumps({"jsonrpc": "2.0", "id": 1, **result}).encode()

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        for i in range(0, len(body), 7):
            await send({"type": "http.response.body", "body": body[i:i + 7],
                "more_body": i + 7 < len(body)})

    monkeypatch.delenv("INTERNET_HANDS_API_KEY", raising=False)
    monkeypatch.setattr("internet_hands.mcp_gateway.authenticate_secret", lambda *_: _gateway_identity())
    store = _FakeStore()
    status, headers, forwarded = await _request(MCPGatewayASGI(inner, store=store),
        headers=[(b"authorization", b"Bearer local-test-only")],
        body=b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"mesh_execute","arguments":{}}}')
    assert status == 200 and forwarded == body
    assert headers["x-request-id"] == store.finished[0]["request_id"]
    assert len(store.charged) == len(store.finished) == 1
    assert store.finished[0]["status"] == expected
    assert current_auth.get() is None


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
    assert headers["x-credits-reserved"] == "3"
    assert len(store.charged) == 1
    assert store.charged[0]["tool_name"] == "gaming_profile"
    assert store.charged[0]["arguments"] == {"game": "mlbb"}
    assert len(store.finished) == 1
    assert store.finished[0]["status"] == "ok"



async def _empty_receive() -> dict[str, Any]:
    return {"type": "http.disconnect"}


async def _caller_inner_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    del receive
    record_usage("public_search_call")
    record_usage("public_search_result", 3)
    record_provider_call("brave")
    response = JSONResponse({"ok": True})
    await response(scope, _empty_receive, send)


@pytest.mark.asyncio
async def test_gateway_settles_measured_caller_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = AuthIdentity(
        user_id="usr_1",
        api_key_id="key_1",
        scopes=["mcp:read", "mcp:execute"],
        plan_slug="builder",
        rpm_limit=60,
        source="api_key",
    )
    # Raw caller quote is 10 units; the hosted wallet reserves 3x.
    store = _FakeStore(reserved=30)
    monkeypatch.setattr(
        "internet_hands.mcp_gateway.authenticate_secret",
        lambda _store, _secret: identity,
    )
    app = MCPGatewayASGI(_caller_inner_app, store=store)  # type: ignore[arg-type]
    body = (
        b'{"jsonrpc":"2.0","id":1,"method":"tools/call",'
        b'"params":{"name":"phone_caller_lookup","arguments":'
        b'{"number":"+14155552671","public_search":true,"max_results":8}}}'
    )

    status, headers, _ = await _request(
        app,
        headers=[
            (b"host", b"mcp.example.test"),
            (b"authorization", b"Bearer ih_live_fake"),
        ],
        body=body,
    )

    assert status == 200
    assert headers["x-credits-reserved"] == "30"
    # finish_usage receives raw measured work; ControlStore applies 3x once.
    assert store.finished[0]["actual_credits"] == 9
    measured = store.finished[0]["execution_usage"]
    assert measured["counters"]["public_search_call"] == 1
    assert measured["counters"]["public_search_result"] == 3
    assert measured["provider_calls"]["brave"] == 1



async def _raising_inner_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    del scope, receive, send
    raise RuntimeError("inner app exploded")


async def _cancelled_inner_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    del scope, receive, send
    raise asyncio.CancelledError()


def _gateway_identity() -> AuthIdentity:
    return AuthIdentity(
        user_id="usr_1",
        api_key_id="key_1",
        scopes=["mcp:read", "mcp:execute"],
        plan_slug="pro",
        rpm_limit=240,
        source="api_key",
        concurrent_limit=10,
    )


@pytest.mark.asyncio
async def test_gateway_marks_uncaught_app_failure_as_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _FakeStore()
    monkeypatch.setattr(
        "internet_hands.mcp_gateway.authenticate_secret",
        lambda _store, _secret: _gateway_identity(),
    )
    app = MCPGatewayASGI(_raising_inner_app, store=store)  # type: ignore[arg-type]
    body = (
        b'{"jsonrpc":"2.0","id":1,"method":"tools/call",'
        b'"params":{"name":"mesh_execute","arguments":{"ref":"nativeweb:search"}}}'
    )

    with pytest.raises(RuntimeError, match="inner app exploded"):
        await _request(
            app,
            headers=[
                (b"host", b"mcp.example.test"),
                (b"authorization", b"Bearer ih_live_fake"),
            ],
            body=body,
        )

    assert store.finished[0]["status"] == "error"


@pytest.mark.asyncio
async def test_gateway_marks_cancelled_app_as_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _FakeStore()
    monkeypatch.setattr(
        "internet_hands.mcp_gateway.authenticate_secret",
        lambda _store, _secret: _gateway_identity(),
    )
    app = MCPGatewayASGI(_cancelled_inner_app, store=store)  # type: ignore[arg-type]
    body = (
        b'{"jsonrpc":"2.0","id":1,"method":"tools/call",'
        b'"params":{"name":"mesh_execute","arguments":{"ref":"nativeweb:search"}}}'
    )

    with pytest.raises(asyncio.CancelledError):
        await _request(
            app,
            headers=[
                (b"host", b"mcp.example.test"),
                (b"authorization", b"Bearer ih_live_fake"),
            ],
            body=body,
        )

    assert store.finished[0]["status"] == "cancelled"
