from __future__ import annotations

import asyncio
import os
import time
from typing import Any
from urllib.parse import quote

import httpx

from .tool_mesh import ToolDescriptor

_TERMINAL_APIFY = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
_MUTATING_HINTS = (
    "CREATE",
    "DELETE",
    "REMOVE",
    "UPDATE",
    "EDIT",
    "SEND",
    "POST",
    "PUBLISH",
    "UPLOAD",
    "MOVE",
    "ARCHIVE",
    "INVITE",
    "TRANSFER",
    "PURCHASE",
    "PAY",
    "CANCEL",
)


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload and len(payload) <= 4:
        return payload.get("data")
    return payload


def _side_effecting(tool_id: str) -> bool:
    upper = tool_id.upper()
    return any(
        f"_{hint}_" in f"_{upper}_" or upper.endswith(f"_{hint}")
        for hint in _MUTATING_HINTS
    )


class _HttpProvider:
    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self.client = client

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self.client is not None:
            response = await self.client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        timeout = kwargs.pop("timeout", 30.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response


class ApifyToolProvider(_HttpProvider):
    name = "apify"

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str = "https://api.apify.com/v2",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client=client)
        self.token = token if token is not None else os.getenv("APIFY_TOKEN", "").strip()
        self.base_url = base_url.rstrip("/")

    def _headers(self, *, require_auth: bool = False) -> dict[str, str]:
        if require_auth and not self.token:
            raise RuntimeError("APIFY_TOKEN is required to execute Actors")
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @staticmethod
    def _actor_id(tool_id: str) -> str:
        return tool_id.replace("/", "~", 1)

    @staticmethod
    def _descriptor(item: dict[str, Any]) -> ToolDescriptor:
        username = str(item.get("username") or item.get("userUsername") or "").strip()
        name = str(item.get("name") or "").strip()
        tool_id = f"{username}/{name}" if username and name else str(item.get("id") or name)
        title = str(item.get("title") or name or tool_id)
        metadata = {
            key: item[key]
            for key in ("id", "notice", "badge", "categories", "stats", "pricingInfos")
            if key in item
        }
        input_schema = item.get("inputSchema") or item.get("input_schema") or {}
        return ToolDescriptor(
            ref=f"apify:{tool_id}",
            provider="apify",
            tool_id=tool_id,
            name=title,
            description=str(item.get("description") or ""),
            input_schema=input_schema if isinstance(input_schema, dict) else {},
            output_schema={},
            tags=[str(value) for value in item.get("categories") or []],
            requires_auth=True,
            side_effecting=False,
            metadata=metadata,
        )

    async def status(self) -> dict[str, Any]:
        return {
            "configured": bool(self.token),
            "searchable": True,
            "executable": bool(self.token),
            "kind": "actor-marketplace",
            "base_url": self.base_url,
        }

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        response = await self._request(
            "GET",
            f"{self.base_url}/store",
            params={
                "search": query,
                "limit": max(1, min(limit, 50)),
                "responseFormat": "agent",
                "includeUnrunnableActors": "false",
            },
            headers=self._headers(),
        )
        payload = response.json()
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        items = data.get("items", []) if isinstance(data, dict) else []
        return [self._descriptor(item) for item in items if isinstance(item, dict)]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        actor_id = quote(self._actor_id(tool_id), safe="~")
        response = await self._request(
            "GET",
            f"{self.base_url}/actors/{actor_id}",
            headers=self._headers(),
        )
        payload = _unwrap(response.json())
        if not isinstance(payload, dict):
            raise TypeError("Apify returned an invalid Actor descriptor")
        descriptor = self._descriptor(payload)
        descriptor.tool_id = tool_id
        descriptor.ref = f"apify:{tool_id}"
        return descriptor

    async def execute(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        account: str | None = None,
        wait_seconds: int = 30,
        timeout_seconds: int = 60,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del account
        actor_id = quote(self._actor_id(tool_id), safe="~")
        options = options or {}
        allowed_options = {
            "build",
            "memory",
            "timeout",
            "maxItems",
            "maxTotalChargeUsd",
        }
        params = {key: value for key, value in options.items() if key in allowed_options}
        response = await self._request(
            "POST",
            f"{self.base_url}/actors/{actor_id}/runs",
            json=arguments,
            params=params,
            headers={**self._headers(require_auth=True), "Content-Type": "application/json"},
            timeout=float(timeout_seconds),
        )
        run = _unwrap(response.json())
        if not isinstance(run, dict):
            raise TypeError("Apify returned an invalid run payload")
        run_id = str(run.get("id") or "")
        if not run_id:
            raise RuntimeError("Apify run did not return an id")

        if wait_seconds > 0:
            run = await self._wait_run(run_id, wait_seconds=wait_seconds)
        status = str(run.get("status") or "RUNNING").upper()
        dataset_id = run.get("defaultDatasetId")
        if status == "SUCCEEDED":
            normalized = "completed"
        elif status in {"FAILED", "ABORTED", "TIMED-OUT"}:
            normalized = "failed"
        else:
            normalized = "running"
        data: Any = run
        if normalized == "completed" and dataset_id:
            data = await self.result_page(str(dataset_id), offset=0, limit=100)
        return {
            "status": normalized,
            "job_id": run_id,
            "result_id": str(dataset_id) if dataset_id else None,
            "data": data,
            "error": (
                None
                if normalized != "failed"
                else str(run.get("statusMessage") or status)
            ),
            "metadata": {"actor": tool_id, "provider_status": status},
        }

    async def _wait_run(self, run_id: str, *, wait_seconds: int) -> dict[str, Any]:
        deadline = time.monotonic() + wait_seconds
        while True:
            latest = await self.job_status(run_id, wait_seconds=0)
            status = str(latest.get("status") or "").upper()
            if status in _TERMINAL_APIFY or time.monotonic() >= deadline:
                return latest
            await asyncio.sleep(min(1.0, max(0.05, deadline - time.monotonic())))

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        if wait_seconds > 0:
            return await self._wait_run(job_id, wait_seconds=wait_seconds)
        response = await self._request(
            "GET",
            f"{self.base_url}/actor-runs/{quote(job_id, safe='')}",
            headers=self._headers(require_auth=True),
        )
        payload = _unwrap(response.json())
        if not isinstance(payload, dict):
            raise TypeError("Apify returned an invalid run status")
        return payload

    async def result_page(
        self, result_id: str, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        page_limit = max(1, min(limit, 1000))
        response = await self._request(
            "GET",
            f"{self.base_url}/datasets/{quote(result_id, safe='')}/items",
            params={"clean": "true", "offset": max(0, offset), "limit": page_limit},
            headers=self._headers(require_auth=True),
        )
        payload = response.json()
        items = payload if isinstance(payload, list) else _unwrap(payload)
        if not isinstance(items, list):
            raise TypeError("Apify returned invalid dataset items")
        return {
            "result_id": result_id,
            "offset": max(0, offset),
            "limit": page_limit,
            "items": items,
        }


class ComposioToolProvider(_HttpProvider):
    name = "composio"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = "https://backend.composio.dev/api/v3.1",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client=client)
        self.api_key = (
            api_key if api_key is not None else os.getenv("COMPOSIO_API_KEY", "").strip()
        )
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("COMPOSIO_API_KEY is not configured")
        return {"x-api-key": self.api_key, "Accept": "application/json"}

    @staticmethod
    def _descriptor(item: dict[str, Any]) -> ToolDescriptor:
        slug = str(item.get("slug") or item.get("tool_slug") or "").strip()
        toolkit = item.get("toolkit") if isinstance(item.get("toolkit"), dict) else {}
        tags = [str(value) for value in item.get("tags") or []]
        if toolkit.get("slug"):
            tags.append(str(toolkit["slug"]))
        input_schema = item.get("input_parameters") or item.get("input_schema") or {}
        output_schema = item.get("output_parameters") or item.get("output_schema") or {}
        return ToolDescriptor(
            ref=f"composio:{slug}",
            provider="composio",
            tool_id=slug,
            name=str(item.get("name") or item.get("human_description") or slug),
            description=str(item.get("description") or item.get("human_description") or ""),
            input_schema=input_schema if isinstance(input_schema, dict) else {},
            output_schema=output_schema if isinstance(output_schema, dict) else {},
            tags=tags,
            requires_auth=not bool(item.get("no_auth", False)),
            side_effecting=_side_effecting(slug),
            metadata={
                "version": item.get("version"),
                "toolkit": toolkit,
                "scopes": item.get("scopes") or [],
                "deprecated": bool(item.get("is_deprecated", False)),
            },
        )

    async def status(self) -> dict[str, Any]:
        return {
            "configured": bool(self.api_key),
            "searchable": bool(self.api_key),
            "executable": bool(self.api_key),
            "kind": "connected-app-tool-catalog",
            "base_url": self.base_url,
        }

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        response = await self._request(
            "GET",
            f"{self.base_url}/tools",
            params={"query": query, "limit": max(1, min(limit, 50))},
            headers=self._headers(),
        )
        payload = response.json()
        items = payload.get("items", []) if isinstance(payload, dict) else []
        return [self._descriptor(item) for item in items if isinstance(item, dict)]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        response = await self._request(
            "GET",
            f"{self.base_url}/tools/{quote(tool_id, safe='')}",
            headers=self._headers(),
        )
        payload = _unwrap(response.json())
        if not isinstance(payload, dict):
            raise TypeError("Composio returned an invalid tool descriptor")
        return self._descriptor(payload)

    async def execute(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        account: str | None = None,
        wait_seconds: int = 30,
        timeout_seconds: int = 60,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del wait_seconds
        options = options or {}
        body: dict[str, Any] = {"arguments": arguments}
        if account:
            body["connected_account_id"] = account
        for key in ("user_id", "custom_auth_params", "custom_connection_data", "version"):
            if key in options:
                body[key] = options[key]
        response = await self._request(
            "POST",
            f"{self.base_url}/tools/execute/{quote(tool_id, safe='')}",
            json=body,
            headers={**self._headers(), "Content-Type": "application/json"},
            timeout=float(timeout_seconds),
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("Composio returned an invalid execution payload")
        successful = bool(payload.get("successful", payload.get("error") in (None, "")))
        return {
            "status": "completed" if successful else "failed",
            "job_id": None,
            "result_id": None,
            "data": payload.get("data", payload),
            "error": (
                None if successful else str(payload.get("error") or "tool execution failed")
            ),
            "metadata": {
                "tool": tool_id,
                "log_id": payload.get("log_id"),
                "session_info": payload.get("session_info"),
            },
        }

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        del job_id, wait_seconds
        raise NotImplementedError(
            "Composio direct tools do not expose generic mesh job handles"
        )

    async def result_page(
        self, result_id: str, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        del result_id, offset, limit
        raise NotImplementedError("Composio direct tools return results inline")


def build_default_providers() -> list[ApifyToolProvider | ComposioToolProvider]:
    return [ApifyToolProvider(), ComposioToolProvider()]
