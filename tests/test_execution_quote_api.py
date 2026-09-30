from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from internet_hands import playground_api
from internet_hands.control_store import AuthIdentity, ControlStore

IDENTITY = AuthIdentity("owner", None, ["mcp:execute"], "free", 100, "session", 10)


def test_quote_is_private_read_only_and_matches_execution_inputs(monkeypatch):
    store = ControlStore("unused")
    monkeypatch.setattr(store, "account_snapshot", lambda owner: {"monthly_credits": 100, "reserved_credits": 20})
    monkeypatch.setattr(playground_api, "store", store)
    monkeypatch.setattr(playground_api, "_playground_identity", lambda request, body: IDENTITY)
    monkeypatch.setattr(playground_api, "validate_public_http_url", lambda url: None)
    app = FastAPI()
    app.include_router(playground_api.router)
    client = TestClient(app)
    body = {"operation": "crawl", "url": "https://example.com", "max_pages": 2}
    response = client.post("/api/playground/quote", json=body)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    quote = response.json()["quote"]
    args = playground_api.playground_arguments(body)
    assert quote["quote_revision"] == store.quote_tool_call(identity=IDENTITY, tool_name="playground:crawl",
                                                           arguments=args)["quote_revision"]
    assert quote["available_credits"] == 80
    assert quote["maximum_charge_credits"] == quote["credits"]
    assert args["paid_recovery"] is False
    assert client.post("/api/playground/quote", content="[").status_code == 400
    assert client.post("/api/playground/quote", json={"operation": "crawl"}).status_code == 400
    assert client.post("/api/playground/quote", content="x" * 65537).status_code == 413


def test_disabled_paid_recovery_never_calls_a_paid_provider(monkeypatch):
    async def unavailable(*args, **kwargs):
        raise RuntimeError("search unavailable")

    def forbidden():
        raise AssertionError("A disabled paid route must not be constructed")

    monkeypatch.setattr(playground_api, "brave_search", unavailable)
    monkeypatch.setattr(playground_api, "FirecrawlToolProvider", forbidden)
    with pytest.raises(RuntimeError, match="Paid recovery is disabled"):
        asyncio.run(playground_api._discover_search_sources("example", count=10, timeout=5, paid_recovery=False))
