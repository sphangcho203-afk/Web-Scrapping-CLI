import json

import pytest

from internet_hands import control_api
from internet_hands.control_store import SCHEMA_SQL


def test_connection_schema_separates_public_and_secret_config() -> None:
    assert "CREATE TABLE IF NOT EXISTS ih_connections" in SCHEMA_SQL
    assert "secret_config jsonb" in SCHEMA_SQL
    assert "auth_type text" in SCHEMA_SQL
    assert "transport text" in SCHEMA_SQL


class _Request:
    def __init__(self, body: dict):
        self.body = body

    async def json(self) -> dict:
        return self.body


class _Store:
    def __init__(self):
        self.calls = []
        self.checks = []
        self.enabled = []

    def create_connection(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": "con_fixture", "name": kwargs["name"],
                "header_names": kwargs["config"]["header_names"]}

    def get_connection_private(self, user_id, connection_id):
        if user_id != "usr_fixture" or connection_id != "con_fixture":
            return None
        return {
            "id": connection_id,
            "user_id": user_id,
            "name": "Provider",
            "endpoint_url": "https://example.com/mcp",
            "transport": "streamable_http",
            "auth_type": "bearer",
            "secret_config": {"headers": {"Authorization": "Bearer fixture-token"}},
        }

    def update_connection_check(self, user_id, connection_id, **kwargs):
        self.checks.append((user_id, connection_id, kwargs))

    def set_connection_enabled(self, user_id, connection_id, enabled):
        self.enabled.append((user_id, connection_id, enabled))
        return user_id == "usr_fixture" and connection_id == "con_fixture"


@pytest.fixture
def connection_store(monkeypatch):
    store = _Store()
    monkeypatch.setattr(control_api, "store", store)
    monkeypatch.setattr(control_api, "_require_user", lambda _request: {
        "id": "usr_fixture", "email_verified": True,
    })
    monkeypatch.setattr(control_api, "validate_public_http_url", lambda url: url)
    return store


async def test_existing_oauth_token_becomes_private_authorization_header(connection_store):
    response = await control_api.create_connection_endpoint(_Request({
        "name": "Provider", "url": "https://example.com/mcp", "auth_type": "oauth",
        "secret": "fixture-access-token",
    }))
    saved = connection_store.calls[0]
    assert saved["auth_type"] == "oauth"
    assert saved["secret_config"] == {"headers": {"Authorization": "Bearer fixture-access-token"}}
    assert saved["config"] == {"header_names": ["Authorization"], "oauth": None}
    assert "fixture-access-token" not in json.dumps(response)


async def test_curl_import_previews_redacted_then_saves_headers(connection_store):
    body = {"name": "Provider", "command": (
        "curl https://example.com/mcp -H 'Authorization: Bearer fixture-access-token'"
    )}
    preview = await control_api.import_connection_curl(_Request(body))
    assert preview["connection"]["header_names"] == ["Authorization"]
    assert not connection_store.calls
    assert "fixture-access-token" not in json.dumps(preview)

    saved = await control_api.import_connection_curl(_Request({**body, "save": True}))
    assert saved["saved"] is True
    assert connection_store.calls[0]["secret_config"] == {
        "headers": {"Authorization": "Bearer fixture-access-token"}
    }
    assert "fixture-access-token" not in json.dumps(saved)


@pytest.mark.asyncio
async def test_connection_probe_persists_live_tool_health(connection_store, monkeypatch):
    async def probe(_connection):
        return {
            "ok": True,
            "tool_count": 2,
            "tools": [
                {
                    "ref": "mcp:con_fixture::search",
                    "name": "Search",
                    "description": "Search public data",
                    "side_effecting": False,
                    "requires_auth": True,
                }
            ],
            "source": {"connection_id": "con_fixture"},
        }

    monkeypatch.setattr(control_api, "probe_saved_connection", probe)

    response = await control_api.test_connection_endpoint("con_fixture", _Request({}))

    assert response["ok"] is True
    assert response["tool_count"] == 2
    assert response["tools"][0]["name"] == "Search"
    assert connection_store.checks == [
        (
            "usr_fixture",
            "con_fixture",
            {"status": "ok", "tool_count": 2, "error": None},
        )
    ]


@pytest.mark.asyncio
async def test_connection_probe_persists_bounded_failure(connection_store, monkeypatch):
    async def probe(_connection):
        raise RuntimeError("upstream MCP rejected initialize")

    monkeypatch.setattr(control_api, "probe_saved_connection", probe)

    response = await control_api.test_connection_endpoint("con_fixture", _Request({}))

    assert response["ok"] is False
    assert response["status"] == "error"
    assert "rejected initialize" in response["error"]
    assert connection_store.checks[0][2]["status"] == "error"
    assert connection_store.checks[0][2]["tool_count"] == 0


@pytest.mark.asyncio
async def test_connection_can_be_paused_without_deleting_secret_state(connection_store):
    response = await control_api.update_connection_endpoint(
        "con_fixture", _Request({"enabled": False})
    )

    assert response == {"ok": True, "enabled": False}
    assert connection_store.enabled == [("usr_fixture", "con_fixture", False)]
