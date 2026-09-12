from __future__ import annotations

import json

import httpx
import pytest

from internet_hands.sandbox_models import SandboxSpec
from internet_hands.vercel_sandbox import VercelSandboxProvider


def _provider(handler) -> tuple[VercelSandboxProvider, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = VercelSandboxProvider(
        token="test-token",
        project_id="prj_test",
        team_id="team_test",
        client=client,
    )
    return provider, client


@pytest.mark.asyncio
async def test_create_uses_network_boundary_and_published_ports() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["team"] = request.url.params.get("teamId")
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": {
                    "sandbox": {"name": "workbench", "status": "running"},
                    "session": {"id": "sbx_create", "status": "running"},
                    "routes": [{"port": 3000, "url": "https://workbench.example"}],
                }
            },
        )

    provider, client = _provider(handler)
    try:
        ref = await provider.create(SandboxSpec(name="workbench", ports=[3000]))
    finally:
        await client.aclose()

    assert seen["method"] == "POST"
    assert seen["path"] == "/v3/sandboxes"
    assert seen["team"] == "team_test"
    assert seen["auth"] == "Bearer test-token"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["projectId"] == "prj_test"
    assert body["ports"] == [3000]
    assert "127.0.0.0/8" in body["networkPolicy"]["deniedCIDRs"]
    assert ref.session_id == "sbx_create"
    assert ref.routes[0]["url"] == "https://workbench.example"


@pytest.mark.asyncio
async def test_detached_command_and_process_controls_use_documented_endpoints() -> None:
    requests: list[tuple[str, str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body))
        if request.url.path.endswith("/cmd") and request.method == "POST":
            return httpx.Response(200, json={"command": {"id": "cmd_bg"}})
        if request.url.path.endswith("/cmd/cmd_bg"):
            return httpx.Response(200, json={"command": {"id": "cmd_bg", "exitCode": None}})
        if request.url.path.endswith("/cmd/cmd_bg/kill"):
            return httpx.Response(200, json={"command": {"id": "cmd_bg"}})
        return httpx.Response(500, json={"unexpected": request.url.path})

    provider, client = _provider(handler)
    try:
        started = await provider.start(
            "sbx_test",
            "python",
            ["-m", "http.server", "3000"],
            timeout_ms=1_800_000,
        )
        status = await provider.command("sbx_test", "cmd_bg")
        killed = await provider.kill_command("sbx_test", "cmd_bg", signal=15)
    finally:
        await client.aclose()

    assert started.command_id == "cmd_bg"
    first = requests[0]
    assert first[0:2] == ("POST", "/v2/sandboxes/sessions/sbx_test/cmd")
    assert first[2] is not None
    assert first[2]["wait"] is False
    assert first[2]["logs"] is False
    assert first[2]["timeout"] == 1_800_000
    assert status["command"]["id"] == "cmd_bg"
    assert killed["command"]["id"] == "cmd_bg"
    assert requests[-1][2] == {"signal": 15}


@pytest.mark.asyncio
async def test_command_history_and_logs_are_bounded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/cmd"):
            return httpx.Response(200, json={"commands": [{"id": "cmd_a"}, {"id": "cmd_b"}]})
        if request.url.path.endswith("/cmd/cmd_a/logs"):
            return httpx.Response(
                200,
                content=b'{"stream":"stdout","data":"hello"}\nplain-line\n',
                headers={"content-type": "application/x-ndjson"},
            )
        return httpx.Response(500)

    provider, client = _provider(handler)
    try:
        history = await provider.list_commands("sbx_test")
        logs = await provider.command_logs("sbx_test", "cmd_a", max_bytes=100)
        short_logs = await provider.command_logs("sbx_test", "cmd_a", max_bytes=10)
    finally:
        await client.aclose()

    assert [item["id"] for item in history] == ["cmd_a", "cmd_b"]
    assert "hello" in logs["text"]
    assert logs["truncated"] is False
    assert short_logs["truncated"] is True


@pytest.mark.asyncio
async def test_stop_delete_and_fork_lifecycle_endpoints() -> None:
    seen: list[tuple[str, str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.url.path.endswith("/stop"):
            return httpx.Response(200, json={"session": {"id": "sbx_test", "status": "stopped"}})
        if request.method == "DELETE":
            return httpx.Response(200, json={"sandbox": {"name": "workbench"}})
        if request.url.path.endswith("/fork"):
            return httpx.Response(
                200,
                json={
                    "sandbox": {"name": "copy", "status": "running"},
                    "session": {"id": "sbx_fork", "status": "running"},
                    "routes": [{"port": 3000, "url": "https://copy.example"}],
                },
            )
        return httpx.Response(500)

    provider, client = _provider(handler)
    try:
        stopped = await provider.stop("sbx_test")
        deleted = await provider.delete("workbench")
        forked = await provider.fork("workbench", "copy", ports=[3000], vcpus=2)
    finally:
        await client.aclose()

    assert stopped["session"]["status"] == "stopped"
    assert deleted["sandbox"]["name"] == "workbench"
    assert forked.session_id == "sbx_fork"
    assert seen[0][0:2] == ("POST", "/v2/sandboxes/sessions/sbx_test/stop")
    assert seen[1][0:2] == ("DELETE", "/v2/sandboxes/workbench")
    assert seen[2][0:2] == ("POST", "/v2/sandboxes/workbench/fork")
    assert seen[2][2] is not None
    assert seen[2][2]["ports"] == [3000]
