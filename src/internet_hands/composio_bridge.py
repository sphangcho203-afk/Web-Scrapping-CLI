from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from .tool_mesh import ToolDescriptor
from .tool_providers import ComposioToolProvider


def _csv_set(name: str) -> set[str]:
    return {item.strip() for item in os.getenv(name, "").split(",") if item.strip()}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class ComposioBridgeProvider(ComposioToolProvider):
    """Connected-account-aware Composio provider for the public Tool Mesh.

    Discovery can be limited to toolkits with ACTIVE connections. Execution is
    fail-closed by default: project-level connected accounts are never selected
    implicitly unless an operator opts in or explicitly allowlists an account.
    """

    name = "composio"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = "https://backend.composio.dev/api/v3.1",
        client: httpx.AsyncClient | None = None,
        connected_only: bool | None = None,
        allowed_toolkits: set[str] | None = None,
        allowed_accounts: set[str] | None = None,
        allow_project_accounts: bool | None = None,
        expose_account_aliases: bool | None = None,
        connection_ttl_seconds: int | None = None,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url, client=client)
        self.connected_only = (
            _env_bool("INTERNET_HANDS_COMPOSIO_CONNECTED_ONLY", True)
            if connected_only is None
            else connected_only
        )
        self.allowed_toolkits = (
            _csv_set("INTERNET_HANDS_COMPOSIO_TOOLKITS")
            if allowed_toolkits is None
            else {item.strip() for item in allowed_toolkits if item.strip()}
        )
        self.allowed_accounts = (
            _csv_set("INTERNET_HANDS_COMPOSIO_ACCOUNT_ALLOW")
            if allowed_accounts is None
            else {item.strip() for item in allowed_accounts if item.strip()}
        )
        self.allow_project_accounts = (
            _env_bool("INTERNET_HANDS_COMPOSIO_ALLOW_PROJECT_ACCOUNTS", False)
            if allow_project_accounts is None
            else allow_project_accounts
        )
        self.expose_account_aliases = (
            _env_bool("INTERNET_HANDS_COMPOSIO_EXPOSE_ACCOUNT_ALIASES", False)
            if expose_account_aliases is None
            else expose_account_aliases
        )
        self.connection_ttl_seconds = max(
            5,
            connection_ttl_seconds
            if connection_ttl_seconds is not None
            else int(os.getenv("INTERNET_HANDS_COMPOSIO_CONNECTION_TTL", "60")),
        )
        self._connection_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._connection_lock = asyncio.Lock()

    @staticmethod
    def _toolkit_slug(descriptor: ToolDescriptor) -> str:
        toolkit = descriptor.metadata.get("toolkit")
        if isinstance(toolkit, dict):
            return str(toolkit.get("slug") or "").strip().lower()
        if isinstance(toolkit, str):
            return toolkit.strip().lower()
        for tag in descriptor.tags:
            normalized = str(tag).strip().lower()
            if normalized:
                return normalized
        return ""

    @staticmethod
    def _connection_toolkit(item: dict[str, Any]) -> str:
        toolkit = item.get("toolkit")
        if isinstance(toolkit, dict):
            return str(toolkit.get("slug") or toolkit.get("name") or "").strip().lower()
        return str(
            item.get("toolkit_slug")
            or item.get("toolkitSlug")
            or item.get("app_name")
            or ""
        ).strip().lower()

    @staticmethod
    def _connection_alias(item: dict[str, Any]) -> str:
        return str(item.get("alias") or item.get("name") or "").strip()

    @staticmethod
    def _connection_id(item: dict[str, Any]) -> str:
        return str(item.get("id") or item.get("connected_account_id") or "").strip()

    @staticmethod
    def _connection_status(item: dict[str, Any]) -> str:
        return str(item.get("status") or "").strip().upper()

    def _connections_url_candidates(self) -> list[str]:
        base = self.base_url.rstrip("/")
        candidates = [f"{base}/connected_accounts"]
        if "/api/v3.1" in base:
            candidates.append(f"{base.replace('/api/v3.1', '/api/v3')}/connected_accounts")
        return list(dict.fromkeys(candidates))

    async def _request_connections_page(
        self, url: str, *, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        params: dict[str, Any] = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        response = await self._request("GET", url, params=params, headers=self._headers())
        payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            payload = payload["data"]
        if not isinstance(payload, dict):
            raise TypeError("Composio returned an invalid connected-account payload")
        raw_items = payload.get("items") or payload.get("connected_accounts") or []
        items = [item for item in raw_items if isinstance(item, dict)]
        next_cursor = (
            payload.get("next_cursor")
            or payload.get("nextCursor")
            or (payload.get("page_info") or {}).get("next_cursor")
        )
        return items, str(next_cursor) if next_cursor else None

    async def _fetch_connections(self, *, force: bool = False) -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        now = time.monotonic()
        cached = self._connection_cache
        if not force and cached and now - cached[0] < self.connection_ttl_seconds:
            return cached[1]

        async with self._connection_lock:
            now = time.monotonic()
            cached = self._connection_cache
            if not force and cached and now - cached[0] < self.connection_ttl_seconds:
                return cached[1]

            last_error: Exception | None = None
            for url in self._connections_url_candidates():
                try:
                    items: list[dict[str, Any]] = []
                    cursor: str | None = None
                    while True:
                        page, cursor = await self._request_connections_page(url, cursor=cursor)
                        items.extend(page)
                        if not cursor:
                            break
                    active = [
                        item
                        for item in items
                        if self._connection_status(item) in {"", "ACTIVE"}
                        and self._connection_id(item)
                    ]
                    self._connection_cache = (time.monotonic(), active)
                    return active
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    if exc.response.status_code != 404:
                        raise
                except Exception as exc:  # noqa: BLE001 - try documented endpoint fallback
                    last_error = exc
                    break
            if last_error:
                raise last_error
            return []

    def _connection_allowed(self, item: dict[str, Any]) -> bool:
        if not self.allowed_accounts:
            return self.allow_project_accounts
        identifiers = {self._connection_id(item), self._connection_alias(item)}
        return bool(self.allowed_accounts.intersection(value for value in identifiers if value))

    def _active_for_toolkit(
        self, connections: list[dict[str, Any]], toolkit: str
    ) -> list[dict[str, Any]]:
        toolkit = toolkit.lower()
        return [
            item
            for item in connections
            if self._connection_toolkit(item) == toolkit
            and (not self.allowed_toolkits or toolkit in self.allowed_toolkits)
        ]

    def _annotate(
        self,
        descriptor: ToolDescriptor,
        connections: list[dict[str, Any]],
    ) -> ToolDescriptor:
        toolkit = self._toolkit_slug(descriptor)
        candidates = self._active_for_toolkit(connections, toolkit) if toolkit else []
        routing_allowed = (
            not descriptor.requires_auth
            or any(self._connection_allowed(item) for item in candidates)
        )
        descriptor.metadata = {
            **descriptor.metadata,
            "connected": bool(candidates) or not descriptor.requires_auth,
            "connected_account_count": len(candidates),
            "configured": routing_allowed,
            "account_routing": (
                "not_required"
                if not descriptor.requires_auth
                else "configured"
                if routing_allowed
                else "locked"
            ),
        }
        if self.expose_account_aliases and candidates:
            descriptor.metadata["connected_account_aliases"] = [
                alias
                for item in candidates
                if (alias := self._connection_alias(item))
            ]
        return descriptor

    async def status(self) -> dict[str, Any]:
        base = await super().status()
        if not self.api_key:
            return {
                **base,
                "connected_only": self.connected_only,
                "account_routing": "unconfigured",
                "connected_toolkits": [],
            }
        try:
            connections = await self._fetch_connections()
        except Exception as exc:  # noqa: BLE001 - status should degrade safely
            return {
                **base,
                "connected_only": self.connected_only,
                "account_routing": "error",
                "connection_error": str(exc),
                "connected_toolkits": [],
            }
        counts: dict[str, int] = {}
        for item in connections:
            toolkit = self._connection_toolkit(item)
            if toolkit and (not self.allowed_toolkits or toolkit in self.allowed_toolkits):
                counts[toolkit] = counts.get(toolkit, 0) + 1
        return {
            **base,
            "connected_only": self.connected_only,
            "account_routing": (
                "project_accounts_enabled"
                if self.allow_project_accounts
                else "allowlist"
                if self.allowed_accounts
                else "locked"
            ),
            "connected_toolkits": [
                {"toolkit": toolkit, "accounts": count}
                for toolkit, count in sorted(counts.items())
            ],
        }

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        fetch_limit = min(max(limit * 4, limit), 50)
        rows = await super().search(query, limit=fetch_limit)
        connections = await self._fetch_connections() if self.connected_only else []
        output: list[ToolDescriptor] = []
        for descriptor in rows:
            toolkit = self._toolkit_slug(descriptor)
            if self.allowed_toolkits and toolkit not in self.allowed_toolkits:
                continue
            annotated = self._annotate(descriptor, connections)
            if self.connected_only and descriptor.requires_auth and not annotated.metadata["connected"]:
                continue
            output.append(annotated)
            if len(output) >= limit:
                break
        return output

    async def describe(self, tool_id: str) -> ToolDescriptor:
        descriptor = await super().describe(tool_id)
        toolkit = self._toolkit_slug(descriptor)
        if self.allowed_toolkits and toolkit not in self.allowed_toolkits:
            raise PermissionError(f"Composio toolkit blocked by bridge policy: {toolkit or 'unknown'}")
        connections = await self._fetch_connections() if descriptor.requires_auth else []
        annotated = self._annotate(descriptor, connections)
        if self.connected_only and descriptor.requires_auth and not annotated.metadata["connected"]:
            raise PermissionError(
                f"Composio tool is not available through an active connection: {tool_id}"
            )
        return annotated

    async def _resolve_account(
        self,
        descriptor: ToolDescriptor,
        requested: str | None,
    ) -> str | None:
        if not descriptor.requires_auth:
            return None
        connections = await self._fetch_connections()
        toolkit = self._toolkit_slug(descriptor)
        candidates = self._active_for_toolkit(connections, toolkit)

        if requested:
            matches = [
                item
                for item in candidates
                if requested in {self._connection_id(item), self._connection_alias(item)}
            ]
            if not matches:
                raise PermissionError(
                    f"requested Composio account is not active for toolkit: {toolkit or 'unknown'}"
                )
            match = matches[0]
            if not self._connection_allowed(match):
                raise PermissionError("requested Composio account is blocked by bridge policy")
            return self._connection_id(match)

        allowed = [item for item in candidates if self._connection_allowed(item)]
        if not allowed:
            raise PermissionError(
                "Composio account routing is locked; configure "
                "INTERNET_HANDS_COMPOSIO_ACCOUNT_ALLOW or explicitly opt in to project accounts"
            )
        if len(allowed) > 1:
            raise PermissionError(
                f"multiple allowed Composio accounts are active for {toolkit or 'this toolkit'}; "
                "pass an explicit account alias or id"
            )
        return self._connection_id(allowed[0])

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
        descriptor = await self.describe(tool_id)
        resolved = await self._resolve_account(descriptor, account)
        return await super().execute(
            tool_id,
            arguments,
            account=resolved,
            wait_seconds=wait_seconds,
            timeout_seconds=timeout_seconds,
            options=options,
        )
