"""The public catalog must not expose provider routes or promise live availability."""

from fastapi.testclient import TestClient

from internet_hands.saas_app import app


def test_public_catalog_projects_registry_without_provider_details():
    client = TestClient(app)
    response = client.get("/api/public/capabilities")
    assert response.status_code == 200
    capabilities = response.json()["capabilities"]
    assert capabilities
    assert any(item["category"] == "Web intelligence" for item in capabilities)
    assert any(item["category"] == "Game intelligence" for item in capabilities)
    assert all(item["availability"] == "registered" for item in capabilities)
    assert all(item["billing"] == "route_dependent" for item in capabilities)
    assert all("candidates" not in item and "provider" not in item for item in capabilities)
    assert client.get("/capabilities").status_code == 200
