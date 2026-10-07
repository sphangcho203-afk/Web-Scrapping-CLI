"""Official client + real OAuth routes + native tool mesh, with isolated fake storage/compute."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientMetadata

from internet_hands import control_api, oauth_compat, playground_api, sandbox_api, tool_mcp
from internet_hands.auth import authenticate_secret, current_auth, sha256_text
from internet_hands.control_store import AuthIdentity, ControlStore
from internet_hands.mcp_customer import MCPPathMiddleware
from internet_hands.mcp_gateway import MCPGatewayASGI
from internet_hands.mcp_server import _transport_security
from internet_hands.mcp_verify import MemoryStorage
from internet_hands.native_sandbox_provider import NativeSandboxToolProvider
from internet_hands.tool_mesh import ToolMesh

KEY = "local-test-key-not-a-production-credential"
IDENTITY = AuthIdentity("owner", "key_test", ["mcp:read", "mcp:execute", "account:read", "monitors:read"], "free", 100, "api_key")


class Store:
    def __init__(self):
        self.codes = {}
        self.tokens = []
        self.reserved = []
        self.finished = []
        self.pricing = ControlStore(dsn=None)

    def get_user(self, user_id):
        return {"id": user_id, "email_verified": True}

    def create_oauth_code(self, **values):
        identity = values.pop("identity")
        self.codes[values["code_hash"]] = {**values, "user_id": identity.user_id, "api_key_id": identity.api_key_id}

    def consume_oauth_code(self, code_hash):
        return self.codes.pop(code_hash, None)

    def create_oauth_token(self, **values):
        self.tokens.append(values)

    def authenticate_access_token(self, hashed):
        return IDENTITY if any(token["access_hash"] == hashed for token in self.tokens) else None

    def authenticate_api_key(self, hashed):
        return IDENTITY if hashed == sha256_text(KEY) else None

    def has_api_key_hash(self, hashed):
        return True

    def account_snapshot(self, user_id):
        return {"monthly_credits": 1000, "purchased_credits": 0, "reserved_credits": 0}

    def quote_tool_call(self, **values):
        return self.pricing.quote_tool_call(**values)

    def reserve_tool_call(self, **values):
        quote = self.quote_tool_call(identity=values["identity"], tool_name=values["tool_name"], arguments=values["arguments"])
        args = values["arguments"] or {}
        if args.get("max_charge_credits", quote["credits"]) < quote["credits"] or args.get("quote_revision", quote["quote_revision"]) != quote["quote_revision"]:
            return self.pricing.reserve_tool_call(**values)
        self.reserved.append(values)
        return quote["credits"]

    def finish_usage(self, request_id, **values):
        self.finished.append({"request_id": request_id, **values})


class Manager:
    def __init__(self):
        self.created = []
        self.deleted = []

    async def create(self, name, **values):
        assert current_auth.get().user_id == "owner"
        assert values["persistent"] is False
        self.created.append(name)
        return {"session_id": "sbx_test"}

    async def shell(self, session_id, command, **values):
        if command == "timeout":
            raise TimeoutError("controlled timeout")
        return {"stdout": "ok\n", "stderr": "stderr\n", "exit_code": 7 if command == "exit 7" else 0}

    async def delete(self, name):
        self.deleted.append(name)


@pytest.mark.asyncio
@pytest.mark.parametrize("command,expected", [("printf ok", "completed"), ("exit 7", "failed"), ("timeout", "failed")])
async def test_official_oauth_client_quote_capped_call_failure_cleanup_and_single_settlement(monkeypatch, command, expected):
    monkeypatch.setenv("INTERNET_HANDS_OAUTH_SIGNING_SECRET", "local-signing-secret")
    monkeypatch.setenv("OPENCRAWL_CREDIT_BURN_MULTIPLIER", "3")
    monkeypatch.delenv("INTERNET_HANDS_API_KEY", raising=False)
    store, manager = Store(), Manager()
    for module in (control_api, playground_api, sandbox_api):
        monkeypatch.setattr(module, "store", store)
    monkeypatch.setattr(control_api, "_session_user", lambda _: None)
    monkeypatch.setattr("internet_hands.mcp_gateway.authenticate_secret", authenticate_secret)
    mesh = ToolMesh([NativeSandboxToolProvider(manager)])
    monkeypatch.setattr(tool_mcp, "get_tool_mesh", lambda: mesh)
    monkeypatch.setattr(sandbox_api, "get_tool_mesh", lambda: mesh)
    server = MCPServer("oauth-native-client-test")
    server.tool()(tool_mcp.mesh_execute)
    raw = server.streamable_http_app(streamable_http_path="/", stateless_http=True,
        json_response=True, transport_security=_transport_security())
    app = FastAPI()
    app.add_middleware(MCPPathMiddleware)
    app.include_router(oauth_compat.router)
    app.include_router(control_api.router)
    app.include_router(sandbox_api.router)
    app.mount("/mcp", MCPGatewayASGI(raw, store=store))
    callback = None

    async def authorize(url):
        nonlocal callback
        parsed = urlsplit(url)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), trust_env=False) as public:
            response = await public.post("https://opencrawl.top/oauth/authorize", data={**params, "api_key": KEY})
        assert response.status_code == 302
        query = parse_qs(urlsplit(response.headers["location"]).query)
        callback = AuthorizationCodeResult(code=query["code"][0], state=query["state"][0], iss=query["iss"][0])

    async def receive_callback():
        return callback

    storage = MemoryStorage()
    oauth = OAuthClientProvider("https://opencrawl.top/mcp", storage=storage,
        client_metadata=OAuthClientMetadata(client_name="Isolated verifier test",
            redirect_uris=["http://127.0.0.1:12345/callback"], scope="mcp:read mcp:execute",
            token_endpoint_auth_method="none"), redirect_handler=authorize, callback_handler=receive_callback)
    async with (
        server.session_manager.run(),
        httpx2.AsyncClient(auth=oauth, transport=httpx2.ASGITransport(app=app), trust_env=False) as client,
        streamable_http_client("https://opencrawl.top/mcp", http_client=client) as streams,
        ClientSession(*streams) as session,
    ):
        await session.initialize()
        assert storage.tokens and len(store.tokens) == 1 and not store.codes
        catalog = await session.list_tools()
        properties = catalog.tools[0].input_schema["properties"]
        assert {"max_charge_credits", "quote_revision"}.issubset(properties)
        assert store.reserved == manager.created == []
        quote_response = await client.post("https://opencrawl.top/api/sandbox/quote",
            json={"command": command, "timeout_seconds": 1})
        assert quote_response.status_code == 200
        quote = quote_response.json()["quote"]
        args = {"ref": "nativesandbox:exec", "arguments": {"command": command,
            "timeout_seconds": 1, "background": False}, "max_charge_credits": quote["credits"],
            "quote_revision": quote["quote_revision"]}
        result = await session.call_tool("mesh_execute", args)
        assert not result.is_error
        assert result.structured_content["status"] == expected
    assert len(store.reserved) == len(store.finished) == len(manager.created) == len(manager.deleted) == 1
    assert store.finished[0]["status"] == ("ok" if expected == "completed" else "error")
    assert store.finished[0]["execution_usage"]["completed"] is (expected == "completed")
    assert current_auth.get() is None
