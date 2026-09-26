import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_public_data_provider import fetched

from internet_hands import public_data_api as module
from internet_hands import public_data_provider
from internet_hands.capability_economics import estimate_call
from internet_hands.execution_meter import execution_usage_snapshot
from internet_hands.tool_mesh import ToolMesh


def test_public_data_dashboard_uses_existing_credentials_and_measured_ledger(monkeypatch):
    ledger = []
    def identity(request, body):
        assert body["api_key_id"] == "key_test"
        return SimpleNamespace(plan_slug="free")
    def reserve(**kwargs):
        return estimate_call(kwargs["tool_name"], kwargs["arguments"], "free").credits
    def finish(request_id, **kwargs):
        ledger.append(kwargs)
    async def fetch(url, **kwargs):
        return fetched('{"score": 5}', "application/json", url)
    monkeypatch.setattr(module, "_playground_identity", identity)
    monkeypatch.setattr(module, "store", SimpleNamespace(reserve_tool_call=reserve, finish_usage=finish))
    monkeypatch.setattr(module, "get_tool_mesh", lambda: ToolMesh([public_data_provider.PublicDataProvider()]))
    monkeypatch.setattr(public_data_provider, "fetch_url", fetch)
    app = FastAPI()
    app.include_router(module.router)
    with TestClient(app) as client:
        response = client.post("/api/public-data/extract", json={"api_key_id": "key_test", "arguments": {"url": "https://source.example/"}})
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["data"] == {"score": 5}
        assert data["usage"] == {"credits_reserved": 5, "credits_charged": 5}
        assert ledger[0]["actual_credits"] == 5
        assert ledger[0]["execution_usage"]["counters"]["public_data_requests"] == 1
        assert client.post("/api/public-data/unknown", json={"arguments": {}}).status_code == 400
        assert client.post("/api/public-data/extract", content=json.dumps([])).status_code == 400
        assert len(ledger) == 1
    assert execution_usage_snapshot()["counters"] == {}


def test_public_data_refuses_missing_identity_before_network_or_reservation(monkeypatch):
    from fastapi import HTTPException
    def identity(*args):
        raise HTTPException(401, "API key required")
    def no_reserve(**kwargs):
        pytest.fail("Unauthenticated run was reserved")
    monkeypatch.setattr(module, "_playground_identity", identity)
    monkeypatch.setattr(module, "store", SimpleNamespace(reserve_tool_call=no_reserve))
    app = FastAPI()
    app.include_router(module.router)
    with TestClient(app) as client:
        response = client.post("/api/public-data/research", json={"arguments": {"urls": ["https://source.example/"]}})
        assert response.status_code == 401


def test_public_search_api_reserves_selected_indexes_and_returns_partial_evidence(monkeypatch):
    ledger = []
    monkeypatch.setattr(module, "_playground_identity", lambda request, body: SimpleNamespace(plan_slug="free"))
    monkeypatch.setattr(module, "store", SimpleNamespace(
        reserve_tool_call=lambda **kwargs: estimate_call(kwargs["tool_name"], kwargs["arguments"], "free").credits,
        finish_usage=lambda request_id, **kwargs: ledger.append(kwargs),
    ))
    monkeypatch.setattr(module, "get_tool_mesh", lambda: ToolMesh([public_data_provider.PublicDataProvider()]))

    async def fetch(url, **kwargs):
        assert kwargs["url_guard"](url)
        if "crossref.org" in url:
            raise RuntimeError("index unavailable")
        return fetched('{"results":[{"id":"https://openalex.org/W42","title":"Research paper"}]}', "application/json", url)

    monkeypatch.setattr(public_data_provider, "fetch_url", fetch)
    app = FastAPI()
    app.include_router(module.router)
    with TestClient(app) as client:
        response = client.post("/api/public-data/search", json={"api_key_id": "key_test", "arguments": {
            "query": "Research paper", "sources": ["openalex", "crossref"], "limit": 3}})
    assert response.status_code == 200
    data = response.json()
    assert data["result"]["partial"] and data["result"]["results"][0]["title"] == "Research paper"
    assert data["usage"] == {"credits_reserved": 8, "credits_charged": 8}
    assert ledger[0]["execution_usage"]["counters"]["public_data_requests"] == 2
