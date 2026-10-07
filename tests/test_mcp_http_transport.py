from __future__ import annotations

import asyncio
import threading
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from mcp.server import MCPServer

from internet_hands import saas_app
from internet_hands.auth import current_auth
from internet_hands.control_store import AuthIdentity
from internet_hands.mcp_customer import MCPPathMiddleware
from internet_hands.mcp_gateway import MCPGatewayASGI
from internet_hands.mcp_server import _transport_security


def _identity() -> AuthIdentity:
    return AuthIdentity("usr_test", "key_test", ["mcp:read", "mcp:execute"], "free", 10, "api_key")


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["/mcp", "/mcp/"])
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_production_routes_challenge_directly_without_redirect(
    monkeypatch: pytest.MonkeyPatch, endpoint: str, method: str,
) -> None:
    monkeypatch.delenv("INTERNET_HANDS_API_KEY", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=saas_app.app),
        base_url="https://opencrawl.top", trust_env=False,
    ) as client:
        response = await client.request(method, endpoint)
    assert response.status_code == 401
    assert "location" not in response.headers
    assert 'resource_metadata="https://opencrawl.top/.well-known/oauth-protected-resource"' in response.headers["www-authenticate"]


class _Store:
    def __init__(self) -> None:
        self.reservations: list[dict[str, Any]] = []
        self.settlements: list[dict[str, Any]] = []

    def reserve_tool_call(self, **kwargs: Any) -> int:
        self.reservations.append(kwargs)
        return 3

    def finish_usage(self, request_id: str, **kwargs: Any) -> None:
        self.settlements.append({"request_id": request_id, **kwargs})


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["2025-03-26", "2025-11-25"])
@pytest.mark.parametrize("endpoint", ["/mcp", "/mcp/"])
async def test_real_sdk_handshake_catalog_and_call(
    monkeypatch: pytest.MonkeyPatch, protocol: str, endpoint: str,
) -> None:
    server = MCPServer("transport-test")

    @server.tool()
    async def caller() -> dict[str, str]:
        """Return the gateway's authenticated caller for the transport test."""
        identity = current_auth.get()
        assert identity is not None
        return {"user_id": identity.user_id}

    raw = server.streamable_http_app(
        streamable_http_path="/", stateless_http=True, json_response=True,
        transport_security=_transport_security(),
    )
    store = _Store()
    monkeypatch.delenv("INTERNET_HANDS_API_KEY", raising=False)
    monkeypatch.setattr("internet_hands.mcp_gateway.authenticate_secret", lambda *_: _identity())
    app = FastAPI()
    app.add_middleware(MCPPathMiddleware)
    app.mount("/mcp", MCPGatewayASGI(raw, store=store))  # type: ignore[arg-type]
    headers = {
        "Authorization": "Bearer local-test-only",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": protocol,
    }
    async with server.session_manager.run(), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://opencrawl.top", trust_env=False,
    ) as client:
        initialized = await asyncio.wait_for(client.post(endpoint, headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": protocol, "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1"},
            },
        }), timeout=2)
        assert initialized.status_code == 200
        assert initialized.json()["result"]["protocolVersion"] == protocol
        assert "mcp-session-id" not in initialized.headers
        notified = await client.post(endpoint, headers=headers, json={
            "jsonrpc": "2.0", "method": "notifications/initialized",
        })
        assert notified.status_code == 202
        catalog = await asyncio.wait_for(client.post(endpoint, headers=headers, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list",
        }), timeout=2)
        assert catalog.status_code == 200
        assert [tool["name"] for tool in catalog.json()["result"]["tools"]] == ["caller"]
        assert not store.reservations
        called = await asyncio.wait_for(client.post(endpoint, headers=headers, json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "caller", "arguments": {}},
        }), timeout=2)
        assert called.status_code == 200
        assert called.json()["result"]["structuredContent"] == {"user_id": "usr_test"}
        assert len(store.reservations) == len(store.settlements) == 1
        assert store.settlements[0]["status"] == "ok"
        rejected = await asyncio.wait_for(client.get(endpoint, headers=headers), timeout=1)
        assert rejected.status_code == 405
        assert rejected.headers["allow"] == "POST"


@pytest.mark.asyncio
async def test_listen_get_still_challenges_unauthenticated_client(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unexpected(*_: Any) -> None:
        raise AssertionError("unauthenticated request reached the SDK")

    monkeypatch.delenv("INTERNET_HANDS_API_KEY", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=MCPGatewayASGI(unexpected)),
        base_url="https://opencrawl.top", trust_env=False,
    ) as client:
        response = await client.get("/", headers={"Accept": "text/event-stream"})
    assert response.status_code == 401
    assert 'resource_metadata="https://opencrawl.top/.well-known/oauth-protected-resource"' in response.headers["www-authenticate"]


@pytest.mark.asyncio
async def test_replayed_body_forwards_subsequent_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        seen.extend([await receive(), await receive()])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    messages = [
        {"type": "http.request", "body": b"{\"method\":\"tools/list\"}", "more_body": False},
        {"type": "http.disconnect"},
    ]

    async def receive() -> dict[str, Any]:
        return messages.pop(0)

    async def send(message: Any) -> None:
        pass

    monkeypatch.setenv("INTERNET_HANDS_API_KEY", "local-test-only")
    await MCPGatewayASGI(inner)({
        "type": "http", "method": "POST", "headers": [(b"authorization", b"Bearer local-test-only")],
    }, receive, send)
    assert seen[0]["body"] == b"{\"method\":\"tools/list\"}"
    assert seen[1] == {"type": "http.disconnect"}


@pytest.mark.asyncio
async def test_partial_body_disconnect_finishes_without_spinning(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = [
        {"type": "http.request", "body": b"{", "more_body": True},
        {"type": "http.disconnect"},
    ]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return messages.pop(0)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def unexpected(*_: Any) -> None:
        raise AssertionError("incomplete body reached SDK")

    monkeypatch.setenv("INTERNET_HANDS_API_KEY", "local-test-only")
    await MCPGatewayASGI(unexpected)({
        "type": "http", "method": "POST", "headers": [(b"authorization", b"Bearer local-test-only")],
    }, receive, send)
    assert sent[0]["status"] == 400
    assert b"request_disconnected" in sent[1]["body"]


@pytest.mark.asyncio
async def test_authentication_database_work_does_not_block_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()
    heartbeat_during_auth: list[bool] = []

    def authenticate(*_: Any) -> AuthIdentity:
        heartbeat_during_auth.append(release.wait(timeout=0.5))
        return _identity()

    async def heartbeat() -> None:
        await asyncio.sleep(0.01)
        release.set()

    async def unexpected(*_: Any) -> None:
        raise AssertionError("listen GET reached SDK")

    monkeypatch.delenv("INTERNET_HANDS_API_KEY", raising=False)
    monkeypatch.setattr("internet_hands.mcp_gateway.authenticate_secret", authenticate)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=MCPGatewayASGI(unexpected)),
        base_url="https://opencrawl.top", trust_env=False,
    ) as client:
        response, _ = await asyncio.gather(
            client.get("/", headers={"Authorization": "Bearer local-test-only"}), heartbeat(),
        )
    assert response.status_code == 405
    assert heartbeat_during_auth == [True]
