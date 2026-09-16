from unittest.mock import AsyncMock, patch

import pytest

from internet_hands.connectors import (
    NeonConnector,
    NeonConnectorError,
    VercelConnector,
    VercelConnectorError,
    VercelNeonBridge,
)


def test_neon_connector_requires_api_key(monkeypatch):
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    monkeypatch.delenv("NEON_API_TOKEN", raising=False)
    connector = NeonConnector()
    with pytest.raises(NeonConnectorError, match="Neon API key is not configured"):
        connector._headers()


def test_vercel_connector_requires_token(monkeypatch):
    monkeypatch.delenv("VERCEL_TOKEN", raising=False)
    monkeypatch.delenv("INTERNET_HANDS_VERCEL_TOKEN", raising=False)
    monkeypatch.delenv("VERCEL_OIDC_TOKEN", raising=False)
    connector = VercelConnector()
    with pytest.raises(VercelConnectorError, match="Vercel token is not configured"):
        connector._headers()


@pytest.mark.asyncio
async def test_neon_connector_list_projects():
    connector = NeonConnector(api_key="test_neon_key")
    mock_projects = [{"id": "proj_123", "name": "production-cluster"}]

    with patch.object(connector, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"projects": mock_projects}
        projects = await connector.list_projects()
        assert projects == mock_projects
        mock_req.assert_called_once_with("GET", "/projects")


@pytest.mark.asyncio
async def test_neon_connector_get_connection_uri():
    connector = NeonConnector(api_key="test_neon_key")
    expected_uri = "postgresql://user:pass@ep-cool-proj-pooler.neon.tech/neondb?sslmode=require"

    with patch.object(connector, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"uri": expected_uri}
        uri = await connector.get_connection_uri("proj_123", pooled=True)
        assert uri == expected_uri
        mock_req.assert_called_once_with(
            "GET",
            "/projects/proj_123/connection_uri",
            params={"database_name": "neondb", "role_name": "neondb_owner", "pooled": "true"},
        )


@pytest.mark.asyncio
async def test_vercel_connector_list_projects():
    connector = VercelConnector(token="test_vercel_token")
    mock_projects = [{"id": "prj_abc", "name": "internet-hands-web"}]

    with patch.object(connector, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"projects": mock_projects}
        projects = await connector.list_projects()
        assert projects == mock_projects
        mock_req.assert_called_once_with("GET", "/v9/projects", params={"limit": 50})


@pytest.mark.asyncio
async def test_vercel_neon_bridge_sync():
    neon = NeonConnector(api_key="neon_key")
    vercel = VercelConnector(token="vercel_token")
    bridge = VercelNeonBridge(neon=neon, vercel=vercel)

    with patch.object(neon, "get_connection_uri", new_callable=AsyncMock) as mock_neon_uri, \
         patch.object(vercel, "upsert_env_vars", new_callable=AsyncMock) as mock_vercel_env:

        mock_neon_uri.side_effect = [
            "postgres://user:pass@ep-pooler.neon.tech/neondb",  # pooled
            "postgres://user:pass@ep-direct.neon.tech/neondb",  # direct
        ]
        mock_vercel_env.return_value = {
            "DATABASE_URL": {"action": "created"},
            "POSTGRES_URL": {"action": "created"},
        }

        res = await bridge.sync_neon_to_vercel(
            neon_project_id="neon_123",
            vercel_project_id_or_name="vercel_456",
        )

        assert res["success"] is True
        assert "DATABASE_URL" in res["synced_keys"]
        assert "INTERNET_HANDS_POSTGRES_DSN" in res["synced_keys"]
        mock_vercel_env.assert_called_once()
