from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from internet_hands import usage_api
from internet_hands.usage_intelligence import normalize_window


def test_usage_endpoint_owner_cache_and_invalid_window(monkeypatch):
    calls = []

    def snapshot(self, user_id, *, window, recent_limit):
        normalize_window(window)
        calls.append((user_id, window, recent_limit))
        return {"totals": {"requests": 0}, "series": []}

    monkeypatch.setattr(usage_api, "_require_user", lambda request: {"id": "authenticated-owner"})
    monkeypatch.setattr(usage_api.UsageIntelligence, "snapshot", snapshot)
    app = FastAPI()
    app.include_router(usage_api.router)
    client = TestClient(app)
    result = client.get("/api/usage/intelligence?window=24h&recent_limit=50")
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "no-store"
    assert calls == [("authenticated-owner", "24h", 50)]
    assert client.get("/api/usage/intelligence?window=all").status_code == 400
    assert client.get("/api/usage/intelligence?recent_limit=51").status_code == 422

    def deny(request):
        raise HTTPException(status_code=401)

    monkeypatch.setattr(usage_api, "_require_user", deny)
    assert client.get("/api/usage/intelligence").status_code == 401
    assert len(calls) == 1
