from __future__ import annotations

import asyncio

import httpx
import pytest
from starlette.responses import JSONResponse

from internet_hands.native_sandbox_provider import NativeSandboxToolProvider
from internet_hands.tool_mesh import ToolMesh
from internet_hands.vercel_runtime_auth import (
    VercelRuntimeAuthMiddleware,
    sandbox_auth_token,
)
from internet_hands.vercel_sandbox import VercelSandboxError, VercelSandboxProvider


@pytest.fixture(autouse=True)
def runtime_environment(monkeypatch):
    for key in ("VERCEL_OIDC_TOKEN", "INTERNET_HANDS_VERCEL_TOKEN", "VERCEL_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("INTERNET_HANDS_SANDBOX_PROJECT_ID", "prj_test")


async def request(app, headers=()):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(VercelRuntimeAuthMiddleware(app)),
        base_url="https://local.test",
    ) as client:
        return await client.get("/", headers=headers)


async def test_warm_provider_uses_current_request_token_and_readiness():
    provider = None
    seen = []
    mesh = ToolMesh([NativeSandboxToolProvider()])
    mesh.provider_status_cache_seconds = 30

    def upstream(req):
        seen.append(req.headers["authorization"])
        return httpx.Response(200, json={"sandbox": {"name": "probe"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as upstream_client:
        async def app(scope, receive, send):
            nonlocal provider
            status = (await mesh.provider_status())["nativesandbox"]
            descriptor = await mesh.providers["nativesandbox"].describe("exec")
            assert descriptor.metadata["configured"] == status["configured"]
            assert not any(k.lower() == b"x-vercel-oidc-token" for k, _ in scope["headers"])
            if provider is None and status["configured"]:
                provider = VercelSandboxProvider(client=upstream_client)
                assert provider._explicit_token is None
            if status["configured"]:
                await provider.delete("probe")
            elif provider is not None:
                with pytest.raises(VercelSandboxError, match="this request"):
                    await provider.delete("probe")
            await JSONResponse({"configured": status["configured"]})(scope, receive, send)

        assert (await request(app)).json() == {"configured": False}
        for value in ("oidc-first", "oidc-refreshed"):
            assert (await request(app, {"x-vercel-oidc-token": value})).json() == {"configured": True}
            assert sandbox_auth_token() is None
        assert (await request(app)).json() == {"configured": False}
    assert seen == ["Bearer oidc-first", "Bearer oidc-refreshed"]


async def test_concurrent_requests_and_worker_threads_keep_credentials_separate():
    entered = 0
    all_entered = asyncio.Event()
    observed = []

    async def app(scope, receive, send):
        nonlocal entered
        initial = sandbox_auth_token()
        entered += 1
        if entered == 3:
            all_entered.set()
        await asyncio.wait_for(all_entered.wait(), timeout=2)
        threaded = await asyncio.to_thread(sandbox_auth_token)
        assert initial == sandbox_auth_token() == threaded
        observed.append(initial)
        await JSONResponse({"ok": True})(scope, receive, send)

    await asyncio.gather(
        request(app, {"x-vercel-oidc-token": "request-a"}),
        request(app, {"x-vercel-oidc-token": "request-b"}),
        request(app),
    )
    assert set(observed) == {"request-a", "request-b", None}
    assert sandbox_auth_token() is None


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_request_failure_always_resets_token(failure):
    async def app(scope, receive, send):
        assert sandbox_auth_token() == "temporary"
        raise failure()

    with pytest.raises(failure):
        await request(app, {"x-vercel-oidc-token": "temporary"})
    assert sandbox_auth_token() is None


@pytest.mark.parametrize("platform,headers", [
    ("0", [("x-vercel-oidc-token", "untrusted")]),
    ("1", [("x-vercel-oidc-token", "has space")]),
    ("1", [("x-vercel-oidc-token", "")]),
    ("1", [("x-vercel-oidc-token", "x" * 8193)]),
    ("1", [("x-vercel-oidc-token", "one"), ("x-vercel-oidc-token", "two")]),
])
async def test_untrusted_or_invalid_header_cannot_configure_sandbox(monkeypatch, platform, headers):
    monkeypatch.setenv("VERCEL", platform)

    async def app(scope, receive, send):
        assert sandbox_auth_token() is None
        assert (await NativeSandboxToolProvider().status())["configured"] is False
        await JSONResponse({"ok": True})(scope, receive, send)

    await request(app, headers)


async def test_environment_and_explicit_credentials_remain_supported(monkeypatch):
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "local-env")
    assert sandbox_auth_token() == "local-env"
    assert VercelSandboxProvider(token="explicit").token == "explicit"

    async def app(scope, receive, send):
        assert sandbox_auth_token() == "runtime"
        assert VercelSandboxProvider(token="explicit").token == "explicit"
        await JSONResponse({"ok": True})(scope, receive, send)

    await request(app, {"x-vercel-oidc-token": "runtime"})
    assert sandbox_auth_token() == "local-env"


async def test_production_mcp_still_requires_customer_authentication():
    from internet_hands.saas_app import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://opencrawl.top",
    ) as client:
        response = await client.post("/mcp", headers={"x-vercel-oidc-token": "provider-token"}, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
        })
    assert response.status_code == 401
    assert "provider-token" not in response.text
    assert sandbox_auth_token() is None
