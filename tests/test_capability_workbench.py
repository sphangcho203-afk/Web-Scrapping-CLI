from __future__ import annotations

from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from internet_hands import capability_api
from internet_hands.capability_packs import Capability, CapabilityCandidate
from internet_hands.control_store import AuthIdentity
from internet_hands.datasets import result_rows

IDENTITY = AuthIdentity("owner", "key_one", ["mcp:execute"], "free", 100, "api_key", 10)


class FakeStore:
    def __init__(self):
        self.reserved = []
        self.finished = []

    def account_snapshot(self, user_id):
        assert user_id == "owner"
        return {"monthly_credits": 100, "purchased_credits": 20, "reserved_credits": 10}

    def quote_tool_call(self, *, identity, tool_name, arguments):
        assert identity.user_id == "owner"
        assert tool_name == "mesh_capability_execute"
        assert arguments["capability"].startswith("web.")
        return {
            "credits": 7,
            "raw_credits": 7,
            "quote_revision": "a" * 64,
            "allowed": True,
            "breakdown": [],
        }

    def reserve_tool_call(self, **kwargs):
        self.reserved.append(kwargs)
        return 7

    def finish_usage(self, request_id, **kwargs):
        self.finished.append((request_id, kwargs))
        return {"request_id": request_id}


class FakeRegistry:
    def __init__(self, *, async_route=False):
        self.async_route = async_route
        cap = Capability(
            id="web.map.site",
            name="Site URL map",
            description="Discover public URLs.",
            pack="web",
            tags=("web", "map"),
            candidates=(CapabilityCandidate(provider="hidden", ref="hidden:map"),),
        )
        async_cap = replace(
            cap,
            id="web.extract.structured",
            name="Structured website extraction",
            tags=("web", "extract"),
        )
        self.capabilities = {cap.id: cap, async_cap.id: async_cap}

    def list(self, *, query=None, pack=None, limit=50):
        rows = [
            cap.to_dict()
            for cap in self.capabilities.values()
            if (not pack or cap.pack == pack)
            and (not query or query.casefold() in (cap.name + " " + cap.description).casefold())
        ]
        return {"capabilities": rows[:limit]}

    async def resolve(self, capability_id):
        cap = self.capabilities[capability_id]
        is_async = capability_id == "web.extract.structured" or self.async_route
        return {
            "capability": cap.to_dict(),
            "resolved": [{
                "available": True,
                "candidate": {"provider": "hidden"},
                "tool": {
                    "ref": "hidden:tool",
                    "provider": "hidden",
                    "input_schema": {
                        "type": "object",
                        "required": ["url"],
                        "properties": {"url": {"type": "string"}},
                    },
                    "output_schema": {"type": "object"},
                    "tags": ["async"] if is_async else ["web", "map"],
                },
            }],
        }

    async def execute(self, capability_id, arguments, **kwargs):
        assert capability_id == "web.map.site"
        assert arguments == {"url": "https://example.com"}
        return {
            "capability": capability_id,
            "selected": "hidden:map",
            "attempts": [{"provider": "hidden", "ref": "hidden:map", "status": "completed"}],
            "execution": {
                "status": "completed",
                "data": {
                    "url": "https://example.com",
                    "links": ["https://example.com/docs", "https://example.com/pricing"],
                },
            },
            "duration_ms": 12,
        }


class FakeDatasets:
    saved = None

    def __init__(self, store):
        self.store = store

    def save(self, user_id, request_id, operation, payload, name):
        FakeDatasets.saved = {
            "user_id": user_id,
            "request_id": request_id,
            "operation": operation,
            "payload": payload,
            "name": name,
        }
        return {
            "id": "ds_capability",
            "request_id": request_id,
            "name": name,
            "operation": operation,
            "row_count": len(payload.get("records") or []),
            "columns": ["value"],
        }


def client(monkeypatch):
    store = FakeStore()
    registry = FakeRegistry()
    monkeypatch.setattr(capability_api, "store", store)
    monkeypatch.setattr(capability_api, "get_capability_registry", lambda: registry)
    monkeypatch.setattr(capability_api, "_require_user", lambda request: {"id": "owner", "email_verified": True})
    monkeypatch.setattr(capability_api, "_require_verified", lambda user: user)
    monkeypatch.setattr(capability_api, "_playground_identity", lambda request, body: IDENTITY)
    monkeypatch.setattr(capability_api, "DatasetStore", FakeDatasets)
    monkeypatch.setattr(capability_api, "raw_credits_from_wallet_reservation", lambda value: value)
    monkeypatch.setattr(capability_api, "wallet_credits_for_raw", lambda value: value)
    monkeypatch.setattr(capability_api, "settle_measured_cost", lambda *args, **kwargs: 3)
    monkeypatch.setattr(capability_api, "start_execution_meter", lambda: object())
    monkeypatch.setattr(capability_api, "reset_execution_meter", lambda token: None)
    monkeypatch.setattr(capability_api, "execution_usage_snapshot", lambda: {"provider_calls": {"hidden": 1}})

    app = FastAPI()
    app.include_router(capability_api.router)
    return TestClient(app), store, registry


def test_capability_listing_is_semantic_and_hides_provider_inventory(monkeypatch):
    http, _, _ = client(monkeypatch)
    response = http.get("/api/capabilities?pack=web")
    assert response.status_code == 200
    row = response.json()["capabilities"][0]
    assert row["id"].startswith("web.")
    assert "candidates" not in row
    assert "provider" not in str(row).casefold()


def test_capability_detail_uses_real_resolved_schema_without_exposing_route(monkeypatch):
    http, _, _ = client(monkeypatch)
    detail = http.get("/api/capabilities/web.map.site").json()
    assert detail["availability"]["interactive_ready"] is True
    assert detail["capability"]["input_schema"]["required"] == ["url"]
    assert "resolved" not in detail
    assert "hidden:map" not in str(detail)


def test_quote_is_read_only_and_async_capabilities_are_not_fake_runnable(monkeypatch):
    http, store, _ = client(monkeypatch)
    quote = http.post(
        "/api/capabilities/web.map.site/quote",
        json={"api_key_id": "key_one", "arguments": {"url": "https://example.com"}},
    )
    assert quote.status_code == 200
    assert quote.headers["cache-control"] == "no-store"
    assert quote.json()["quote"]["credits"] == 7
    assert quote.json()["quote"]["available_credits"] == 110
    assert store.reserved == []

    blocked = http.post(
        "/api/capabilities/web.extract.structured/quote",
        json={"api_key_id": "key_one", "arguments": {"prompt": "Extract prices"}},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "interactive_not_ready"


def test_run_reserves_executes_settles_and_saves_generic_records(monkeypatch):
    http, store, _ = client(monkeypatch)
    response = http.post(
        "/api/capabilities/web.map.site/run",
        json={
            "api_key_id": "key_one",
            "arguments": {"url": "https://example.com"},
            "max_charge_credits": 7,
            "quote_revision": "a" * 64,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["usage"] == {"credits_reserved": 7, "credits_charged": 3, "metered": True}
    assert data["dataset"]["id"] == "ds_capability"
    assert data["result"]["route_attempts"] == [{"status": "completed", "error": None}]
    assert "provider" not in str(data["result"]["route_attempts"]).casefold()
    assert store.reserved[0]["tool_name"] == "mesh_capability_execute"
    assert store.reserved[0]["arguments"]["max_charge_credits"] == 7
    assert store.finished and store.finished[0][1]["status"] == "ok"
    assert [row["value"] for row in FakeDatasets.saved["payload"]["records"]] == [
        "https://example.com/docs", "https://example.com/pricing"
    ]


def test_capability_body_and_arguments_are_bounded(monkeypatch):
    http, _, _ = client(monkeypatch)
    assert http.post("/api/capabilities/web.map.site/quote", content="[").status_code == 400
    assert http.post("/api/capabilities/web.map.site/quote", json=[]).status_code == 400
    assert http.post("/api/capabilities/web.map.site/quote", json={}).status_code == 422
    assert http.post(
        "/api/capabilities/web.map.site/quote",
        content="x" * 128001,
        headers={"content-type": "application/json"},
    ).status_code == 413


def test_dataset_row_model_accepts_generic_capability_records():
    rows = result_rows({"records": [{"url": "https://example.com"}, {"value": "second"}]})
    assert [row["record_type"] for row in rows] == ["records", "records"]
    assert rows[0]["url"] == "https://example.com"


def test_owned_availability_is_unmetered_and_hides_route_inventory(monkeypatch):
    from internet_hands.auth import current_auth

    http, store, registry = client(monkeypatch)
    original = registry.resolve
    identities = []

    async def inspect(capability_id):
        identities.append(current_auth.get().user_id)
        return await original(capability_id)

    monkeypatch.setattr(registry, "resolve", inspect)
    response = http.get("/api/capabilities/web.map.site/availability")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"capability": "web.map.site", "available": True,
                               "available_routes": 1, "setup": [], "credits_reserved": 0}
    assert "hidden" not in response.text
    assert identities == ["owner"]
    assert store.reserved == store.finished == []
    assert current_auth.get() is None
    assert http.get("/api/capabilities/missing/availability").status_code == 404


def test_unavailable_workbench_shows_reason_before_quote_or_reservation(monkeypatch):
    from internet_hands.auth import current_auth
    from internet_hands.capability_availability import availability_failure

    http, store, registry = client(monkeypatch)
    identities = []

    async def unavailable(capability_id):
        identities.append(current_auth.get().user_id)
        return {"resolved": [availability_failure("connection_required")]}

    monkeypatch.setattr(registry, "resolve", unavailable)
    detail = http.get("/api/capabilities/web.map.site")
    assert detail.status_code == 200
    assert detail.headers["cache-control"] == "no-store"
    assert detail.json()["availability"]["interactive_ready"] is False
    assert detail.json()["availability"]["reason_codes"] == ["connection_required"]
    assert "Connect an authorized account" in detail.text
    for action in ("quote", "run"):
        response = http.post("/api/capabilities/web.map.site/" + action, json={
            "api_key_id": "key_one", "arguments": {"url": "https://example.com"},
        })
        assert response.status_code == 409
        assert "Connect an authorized account" in response.text
    assert identities == ["owner", "owner", "owner"]
    assert store.reserved == store.finished == []
    assert current_auth.get() is None


def test_availability_inspects_connected_pack_without_enabling_workbench(monkeypatch):
    http, store, registry = client(monkeypatch)
    registry.capabilities["automation.workflow"] = replace(
        registry.capabilities["web.map.site"], id="automation.workflow", pack="connected", read_only=False,
    )
    response = http.get("/api/capabilities/automation.workflow/availability")
    assert response.status_code == 200
    assert response.json()["available"] is True
    assert http.get("/api/capabilities/automation.workflow").status_code == 404
    assert store.reserved == []
