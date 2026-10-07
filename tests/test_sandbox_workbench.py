from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from internet_hands import playground_api, sandbox_api
from internet_hands.auth import current_auth
from internet_hands.control_store import AuthIdentity, ControlStore
from internet_hands.native_sandbox_provider import NativeSandboxToolProvider
from internet_hands.tool_mesh import ToolMesh

IDENTITY = AuthIdentity("owner", "key_one", ["mcp:execute"], "free", 100, "api_key", 10)
INPUT = {"api_key_id": "key_one", "command": "printf ok", "timeout_seconds": 5}


class FakeStore:
    def __init__(self):
        self.reserved = []
        self.finished = []
        self.identity = IDENTITY
        self.fail_settlement = False
        self.pricing = ControlStore(dsn=None)

    def api_key_identity_for_user(self, user_id, key_id):
        return self.identity if user_id == "owner" and key_id == "key_one" else None

    def account_snapshot(self, user_id):
        return {"monthly_credits": 100, "purchased_credits": 0, "reserved_credits": 0}

    def quote_tool_call(self, **kwargs):
        return self.pricing.quote_tool_call(**kwargs)

    def reserve_tool_call(self, **kwargs):
        quote = self.quote_tool_call(identity=kwargs["identity"], tool_name=kwargs["tool_name"], arguments=kwargs["arguments"])
        # Invalid quote/cap checks in the actual store occur before opening the DB.
        args = kwargs["arguments"]
        if args["max_charge_credits"] < quote["credits"] or args["quote_revision"] != quote["quote_revision"]:
            return self.pricing.reserve_tool_call(**kwargs)
        self.reserved.append(kwargs)
        return quote["credits"]

    def finish_usage(self, request_id, **kwargs):
        if self.fail_settlement:
            raise RuntimeError("database down")
        self.finished.append((request_id, kwargs))


class FakeManager:
    def __init__(self):
        self.created = []
        self.deleted = []
        self.stopped = []
        self.exit_code = 0
        self.delete_error = False
        self.stop_error = False
        self.stream_error = False

    async def create(self, name, **kwargs):
        assert current_auth.get().user_id == "owner"
        assert kwargs["persistent"] is False
        self.created.append(name)
        return {"session_id": "sbx_test"}

    async def shell(self, session_id, script, **kwargs):
        if self.stream_error:
            raise RuntimeError("interrupted stream")
        return {"stdout": "ok", "stderr": "stderr-ok", "exit_code": self.exit_code}

    async def delete(self, name):
        if self.delete_error:
            raise RuntimeError("delete unavailable")
        self.deleted.append(name)

    async def stop(self, session_id):
        if self.stop_error:
            raise RuntimeError("stop unavailable")
        self.stopped.append(session_id)


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("OPENCRAWL_CREDIT_BURN_MULTIPLIER", "3")
    store = FakeStore()
    manager = FakeManager()
    mesh = ToolMesh([NativeSandboxToolProvider(manager)])
    monkeypatch.setattr(sandbox_api, "store", store)
    monkeypatch.setattr(playground_api, "store", store)
    monkeypatch.setattr(sandbox_api, "get_tool_mesh", lambda: mesh)
    monkeypatch.setattr(sandbox_api, "_require_user", lambda request: {"id": "owner", "email_verified": True})
    monkeypatch.setattr(playground_api, "_require_user", lambda request: {"id": "owner", "email_verified": True})
    app = FastAPI()
    app.include_router(sandbox_api.router)
    return TestClient(app, headers={"Origin": "http://testserver"}), store, manager


def run_body(http):
    response = http.post("/api/sandbox/quote", json=INPUT)
    assert response.status_code == 200, response.text
    quote = response.json()["quote"]
    return {**INPUT, "allow_execution": True, "max_charge_credits": quote["credits"], "quote_revision": quote["quote_revision"]}


def test_quote_does_not_allocate_or_reserve(setup):
    http, store, manager = setup
    response = http.post("/api/sandbox/quote", json=INPUT)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["quote"]["affordable"] is True
    assert store.reserved == manager.created == []


@pytest.mark.parametrize("exit_code", [0, 7])
def test_owned_execution_settlement_and_cleanup(setup, exit_code):
    http, store, manager = setup
    manager.exit_code = exit_code
    result = http.post("/api/sandbox/run", json=run_body(http)).json()
    assert result["ok"] is (exit_code == 0)
    assert result["result"]["data"]["stdout"] == "ok"
    assert result["result"]["data"]["stderr"] == "stderr-ok"
    assert result["result"]["data"]["exit_code"] == exit_code
    assert result["result"]["cleanup"]["status"] == "deleted"
    assert manager.deleted == manager.created
    assert result["usage"]["settled"] is True
    assert result["usage"]["credits_charged"] <= result["usage"]["credits_reserved"]
    assert len(store.reserved) == len(store.finished) == 1
    assert store.finished[0][1]["actual_credits"] * 3 == result["usage"]["credits_charged"]
    assert store.finished[0][1]["status"] == ("ok" if exit_code == 0 else "error")
    assert current_auth.get() is None


@pytest.mark.parametrize("stop_error", [False, True])
def test_delete_failure_reports_stopped_or_failed_cleanup(setup, stop_error):
    http, _, manager = setup
    manager.delete_error, manager.stop_error = True, stop_error
    result = http.post("/api/sandbox/run", json=run_body(http)).json()
    assert result["result"]["cleanup"]["status"] == ("failed" if stop_error else "stopped")
    assert manager.deleted == []


def test_stream_failure_is_settled_and_cleans_up(setup):
    http, store, manager = setup
    manager.stream_error = True
    result = http.post("/api/sandbox/run", json=run_body(http)).json()
    assert result["ok"] is False
    assert store.finished[0][1]["status"] == "error"
    assert result["usage"]["settled"] is True
    assert manager.deleted == manager.created


@pytest.mark.parametrize("fields", [
    {"command": ""}, {"command": "x" * 50001}, {"command": "\x00"},
    {"timeout_seconds": 16}, {"timeout_seconds": True}, {"timeout_seconds": "5"},
    {"background": True}, {"env": {"TOKEN": "secret"}}, {"api_key_id": "other_user_key"},
])
def test_invalid_or_foreign_inputs_never_allocate(setup, fields):
    http, store, manager = setup
    response = http.post("/api/sandbox/quote", json={**INPUT, **fields})
    assert response.status_code in (409, 422)
    assert store.reserved == manager.created == []


@pytest.mark.parametrize(("field", "value", "status"), [
    ("allow_execution", False, 403), ("max_charge_credits", 0, 409),
    ("max_charge_credits", True, 422), ("quote_revision", "b" * 64, 409),
    ("quote_revision", None, 422), ("command", "printf changed", 409),
])
def test_consent_cap_and_stale_quote_checked_before_compute(setup, field, value, status):
    http, store, manager = setup
    body = {**run_body(http), field: value}
    response = http.post("/api/sandbox/run", json=body)
    assert response.status_code == status, response.text
    assert store.reserved == manager.created == []


def test_cross_origin_cookie_execution_rejected(setup):
    http, store, manager = setup
    response = http.post("/api/sandbox/quote", json=INPUT, headers={"Origin": "https://evil.invalid"})
    assert response.status_code == 403
    assert store.reserved == manager.created == []


def test_read_scope_cannot_execute(setup):
    http, store, manager = setup
    store.identity = AuthIdentity("owner", "key_one", ["mcp:read"], "free", 100, "api_key", 10)
    assert http.post("/api/sandbox/quote", json=INPUT).status_code == 403
    assert store.reserved == manager.created == []


def test_unauthenticated_user_cannot_quote(setup, monkeypatch):
    http, store, manager = setup
    def missing(request):
        raise HTTPException(401, "sign in required")
    monkeypatch.setattr(sandbox_api, "_require_user", missing)
    assert http.post("/api/sandbox/quote", json=INPUT).status_code == 401
    assert store.reserved == manager.created == []


def test_settlement_error_is_not_reported_as_settled(setup):
    http, store, manager = setup
    body = run_body(http)
    store.fail_settlement = True
    response = http.post("/api/sandbox/run", json=body)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "settlement_unavailable"
    assert response.json()["detail"]["request_id"].startswith("req_")
    assert manager.deleted == manager.created
    assert current_auth.get() is None


def test_bearer_auth_can_quote_without_cookie_origin(setup, monkeypatch):
    http, store, manager = setup
    monkeypatch.setattr(playground_api, "authenticate_secret", lambda control, secret: IDENTITY)
    http.headers.pop("origin", None)
    response = http.post("/api/sandbox/quote", json={"command": "printf ok"}, headers={"Authorization": "Bearer test-owned-key"})
    assert response.status_code == 200
    assert store.reserved == manager.created == []


def test_unverified_session_is_blocked(setup, monkeypatch):
    http, store, manager = setup
    monkeypatch.setattr(sandbox_api, "_require_user", lambda request: {"id": "owner", "email_verified": False})
    assert http.post("/api/sandbox/quote", json=INPUT).status_code == 403
    assert store.reserved == manager.created == []


def test_unavailable_provider_never_reserves(setup, monkeypatch):
    http, store, manager = setup
    mesh = sandbox_api.get_tool_mesh()
    monkeypatch.setattr(mesh.providers["nativesandbox"], "_configured", lambda: False)
    response = http.post("/api/sandbox/quote", json=INPUT)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "sandbox_unavailable"
    assert store.reserved == manager.created == []
