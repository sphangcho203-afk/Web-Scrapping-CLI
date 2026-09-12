from __future__ import annotations

import base64
import io
import json
import os
import tarfile
from typing import Any
from urllib.parse import quote

import httpx

from .sandbox_models import CommandResult, SandboxRef, SandboxSpec
from .sandbox_policy import public_network_policy


class VercelSandboxError(RuntimeError):
    pass


class VercelSandboxProvider:
    """Vercel Sandbox provider backed by the documented REST control plane."""

    def __init__(
        self,
        *,
        token: str | None = None,
        project_id: str | None = None,
        team_id: str | None = None,
        base_url: str = "https://api.vercel.com",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token = (
            token
            or os.getenv("VERCEL_OIDC_TOKEN")
            or os.getenv("INTERNET_HANDS_VERCEL_TOKEN")
            or os.getenv("VERCEL_TOKEN")
        )
        self.project_id = (
            project_id
            or os.getenv("INTERNET_HANDS_SANDBOX_PROJECT_ID")
            or os.getenv("VERCEL_PROJECT_ID")
        )
        self.team_id = (
            team_id
            or os.getenv("INTERNET_HANDS_SANDBOX_TEAM_ID")
            or os.getenv("VERCEL_TEAM_ID")
        )
        self.base_url = base_url.rstrip("/")
        self._client = client
        if not self.token:
            raise VercelSandboxError(
                "Vercel sandbox auth is unavailable; deploy on Vercel or set "
                "INTERNET_HANDS_VERCEL_TOKEN for local development"
            )
        if not self.project_id:
            raise VercelSandboxError(
                "sandbox project id is unavailable; set INTERNET_HANDS_SANDBOX_PROJECT_ID"
            )

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(extra or {})
        if self.team_id:
            params["teamId"] = self.team_id
        return params

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.token}"}
        headers.update(kwargs.pop("headers", {}))
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=120)
        try:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                **kwargs,
            )
            if response.is_error:
                detail = response.text[:2000]
                raise VercelSandboxError(
                    f"Vercel Sandbox API {response.status_code} for {path}: {detail}"
                )
            return response
        finally:
            if owns_client:
                await client.aclose()

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise VercelSandboxError("Vercel Sandbox API returned non-JSON data") from exc
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            return data["data"]
        if not isinstance(data, dict):
            return {"value": data}
        return data

    @staticmethod
    def _ref(data: dict[str, Any], name_hint: str) -> SandboxRef:
        sandbox = data.get("sandbox") if isinstance(data.get("sandbox"), dict) else data
        session = data.get("session") if isinstance(data.get("session"), dict) else {}
        session_id = str(
            session.get("id")
            or sandbox.get("sessionId")
            or sandbox.get("session_id")
            or sandbox.get("id")
            or ""
        )
        if not session_id.startswith("sbx_"):
            raise VercelSandboxError("Vercel Sandbox response did not include a session id")
        routes = data.get("routes") if isinstance(data.get("routes"), list) else []
        return SandboxRef(
            name=str(sandbox.get("name") or name_hint),
            session_id=session_id,
            status=str(session.get("status") or sandbox.get("status") or "unknown"),
            routes=[item for item in routes if isinstance(item, dict)],
            raw=data,
        )

    async def create(self, spec: SandboxSpec) -> SandboxRef:
        payload: dict[str, Any] = {
            "name": spec.name,
            "projectId": self.project_id,
            "resources": {"vcpus": spec.vcpus, "memory": spec.memory_mb},
            "timeout": spec.timeout,
            "persistent": spec.persistent,
            "ports": spec.ports,
            "env": spec.env,
            "tags": {"internet-hands": "sandbox", **spec.tags},
            "networkPolicy": public_network_policy(),
        }
        if spec.image:
            payload["image"] = spec.image
        response = await self._request(
            "POST", "/v3/sandboxes", params=self._params(), json=payload
        )
        return self._ref(self._json(response), spec.name)

    async def get(self, name: str, *, resume: bool = True) -> SandboxRef:
        response = await self._request(
            "GET",
            f"/v2/sandboxes/{quote(name, safe='')}",
            params=self._params(
                {"projectId": self.project_id, "resume": str(resume).lower()}
            ),
        )
        return self._ref(self._json(response), name)

    async def exec(
        self,
        session_id: str,
        command: str,
        args: list[str] | None = None,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        sudo: bool = False,
        timeout_ms: int = 30_000,
    ) -> CommandResult:
        payload: dict[str, Any] = {
            "command": command,
            "args": args or [],
            "env": env or {},
            "sudo": sudo,
            "wait": True,
            "logs": True,
            "timeout": timeout_ms,
        }
        if cwd:
            payload["cwd"] = cwd

        headers = {"Authorization": f"Bearer {self.token}"}
        owns_client = self._client is None
        timeout_s = max(120, timeout_ms / 1000 + 15)
        client = self._client or httpx.AsyncClient(timeout=timeout_s)
        events: list[dict[str, Any]] = []
        raw_lines: list[str] = []
        try:
            path = f"/v2/sandboxes/sessions/{quote(session_id, safe='')}/cmd"
            async with client.stream(
                "POST",
                f"{self.base_url}{path}",
                params=self._params(),
                headers=headers,
                json=payload,
            ) as response:
                if response.is_error:
                    body = (await response.aread()).decode("utf-8", errors="replace")[:2000]
                    raise VercelSandboxError(
                        f"Vercel Sandbox command failed with {response.status_code}: {body}"
                    )
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    raw_lines.append(line)
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        item = {"data": line}
                    if isinstance(item, dict):
                        events.append(item)
        finally:
            if owns_client:
                await client.aclose()

        command_obj: dict[str, Any] = {}
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        for event in events:
            candidate = event.get("command")
            if isinstance(candidate, dict):
                command_obj = candidate
            stream = str(event.get("stream") or event.get("type") or "").lower()
            text = event.get("data")
            if text is None:
                text = event.get("text")
            if isinstance(text, str):
                if "stderr" in stream:
                    stderr_parts.append(text)
                elif "stdout" in stream or "log" in stream:
                    stdout_parts.append(text)
        if not stdout_parts and not stderr_parts and raw_lines:
            stdout_parts = raw_lines

        exit_code = command_obj.get("exitCode")
        try:
            parsed_exit = int(exit_code) if exit_code is not None else None
        except (TypeError, ValueError):
            parsed_exit = None
        return CommandResult(
            session_id=session_id,
            command_id=str(command_obj.get("id")) if command_obj.get("id") else None,
            exit_code=parsed_exit,
            stdout="\n".join(stdout_parts),
            stderr="\n".join(stderr_parts),
            events=events,
            raw=command_obj,
        )

    async def read_file(
        self, session_id: str, path: str, *, cwd: str | None = None
    ) -> bytes:
        payload: dict[str, Any] = {"path": path}
        if cwd:
            payload["cwd"] = cwd
        response = await self._request(
            "POST",
            f"/v2/sandboxes/sessions/{quote(session_id, safe='')}/fs/read",
            params=self._params(),
            json=payload,
        )
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            return response.content
        data = response.json()
        if isinstance(data, str):
            return data.encode()
        if isinstance(data, dict):
            value = data.get("content", data.get("data", data.get("value", "")))
            if isinstance(value, str):
                if data.get("encoding") == "base64":
                    return base64.b64decode(value)
                return value.encode()
        return json.dumps(data, ensure_ascii=False).encode()

    async def write_file(
        self,
        session_id: str,
        path: str,
        content: bytes,
        *,
        cwd: str | None = None,
    ) -> None:
        clean_path = path.lstrip("/")
        if not clean_path or clean_path.startswith("../") or "/../" in clean_path:
            raise ValueError("file path must remain inside the selected working directory")
        archive_buffer = io.BytesIO()
        with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
            info = tarfile.TarInfo(name=clean_path)
            info.size = len(content)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(content))
        headers = {"Content-Type": "application/gzip"}
        if cwd:
            headers["x-cwd"] = cwd
        await self._request(
            "POST",
            f"/v2/sandboxes/sessions/{quote(session_id, safe='')}/fs/write",
            params=self._params(),
            headers=headers,
            content=archive_buffer.getvalue(),
        )

    async def snapshot(self, session_id: str) -> dict[str, object]:
        response = await self._request(
            "POST",
            f"/v2/sandboxes/sessions/{quote(session_id, safe='')}/snapshot",
            params=self._params(),
            json={},
        )
        return self._json(response)
