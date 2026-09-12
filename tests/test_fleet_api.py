from fastapi.testclient import TestClient

from internet_hands.fleet_api import app


def test_fleet_api_fails_closed_without_api_key(monkeypatch):
    monkeypatch.delenv("INTERNET_HANDS_API_KEY", raising=False)
    monkeypatch.delenv("INTERNET_HANDS_ALLOW_UNAUTHENTICATED", raising=False)
    client = TestClient(app)

    response = client.get("/v1/events")

    assert response.status_code == 503


def test_fleet_api_can_read_local_telemetry_in_explicit_local_mode(monkeypatch, tmp_path):
    monkeypatch.delenv("INTERNET_HANDS_API_KEY", raising=False)
    monkeypatch.setenv("INTERNET_HANDS_ALLOW_UNAUTHENTICATED", "1")
    monkeypatch.setenv("INTERNET_HANDS_TELEMETRY_DB", str(tmp_path / "telemetry.db"))
    client = TestClient(app)

    response = client.get("/v1/events")

    assert response.status_code == 200
    assert response.json() == []
