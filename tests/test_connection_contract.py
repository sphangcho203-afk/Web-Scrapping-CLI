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

    def create_connection(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": "con_fixture", "name": kwargs["name"],
                "header_names": kwargs["config"]["header_names"]}


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
