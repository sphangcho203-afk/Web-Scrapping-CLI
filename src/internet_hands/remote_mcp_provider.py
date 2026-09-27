from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shlex
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx2
from mcp import Client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from .auth import current_auth
from .control_store import ControlStore
from .policy import validate_public_http_url
from .tool_mesh import ToolDescriptor


@dataclass(frozen=True, slots=True)
class RemoteMcpSource:
    name: str
    url: str
    transport: str = "streamable_http"
    auth_type: str = "none"
    headers: tuple[tuple[str, str], ...] = ()
    display_name: str | None = None
    connection_id: str | None = None

    @property
    def requires_auth(self) -> bool:
        return self.auth_type != "none" or bool(self.headers)

    def public_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.name,
            "name": self.display_name or self.name,
            "connection_id": self.connection_id,
            "url": self.url,
            "transport": self.transport,
            "auth_type": self.auth_type,
            "requires_auth": self.requires_auth,
            "header_names": [name for name, _ in self.headers],
        }


AUTH_TYPES = {"none", "api_key", "bearer", "headers", "oauth"}
TRANSPORTS = {"streamable_http", "sse"}
_FORBIDDEN_OUTBOUND_HEADERS = {
    "connection",
    "content-length",
    "host",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
ConnectionLoader = Callable[[str], list[dict[str, Any]]]


def _normalize_headers(raw_headers: Any) -> dict[str, str]:
    headers: dict[str, str] = {}
    if isinstance(raw_headers, dict):
        rows = raw_headers.items()
    elif isinstance(raw_headers, list):
        rows = (
            (row.get("name"), row.get("value"))
            for row in raw_headers
            if isinstance(row, dict) and row.get("name")
        )
    else:
        rows = []
    for raw_name, raw_value in rows:
        name = str(raw_name or "").strip()
        if not name:
            continue
        if name.casefold() in _FORBIDDEN_OUTBOUND_HEADERS:
            raise ValueError(f"unsafe outbound MCP header: {name}")
        value = str(raw_value or "")
        if "\r" in value or "\n" in value:
            raise ValueError(f"invalid newline in outbound MCP header: {name}")
        headers[name] = value
    return headers


def _normalize_source(item: dict[str, Any]) -> RemoteMcpSource:
    name = str(item.get("name") or "").strip().lower()
    url = str(item.get("url") or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", name):
        raise ValueError(f"invalid remote MCP source name: {name}")
    if not url:
        raise ValueError("remote MCP source url is required")
    transport = str(item.get("transport") or "streamable_http").strip().lower().replace("-", "_")
    if transport == "streamablehttp":
        transport = "streamable_http"
    if transport not in TRANSPORTS:
        raise ValueError(f"unsupported remote MCP transport: {transport}")
    auth_type = str(item.get("auth_type") or item.get("authentication") or "none").strip().lower()
    aliases = {
        "apikey": "api_key",
        "api-key": "api_key",
        "bearerauth": "bearer",
        "headerauth": "headers",
        "oauth2": "oauth",
    }
    auth_type = aliases.get(auth_type, auth_type)
    if auth_type not in AUTH_TYPES:
        raise ValueError(f"unsupported remote MCP auth type: {auth_type}")
    headers = _normalize_headers(item.get("headers") or {})
    secret = str(item.get("secret") or item.get("token") or item.get("api_key") or "")
    if auth_type == "bearer" and secret:
        headers.setdefault("Authorization", f"Bearer {secret}")
    elif auth_type == "api_key" and secret:
        header_name = str(item.get("header_name") or "X-API-Key").strip()
        if header_name.casefold() in _FORBIDDEN_OUTBOUND_HEADERS:
            raise ValueError(f"unsafe outbound MCP header: {header_name}")
        headers.setdefault(header_name, secret)
    return RemoteMcpSource(
        name=name,
        url=url,
        transport=transport,
        auth_type=auth_type,
        headers=tuple(headers.items()),
    )


def _runtime_source_name(connection_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "_", connection_id.casefold()).strip("_")
    if normalized and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", normalized):
        return normalized
    digest = hashlib.sha256(connection_id.encode("utf-8")).hexdigest()[:16]
    return f"connection_{digest}"


def _source_from_connection(row: dict[str, Any]) -> RemoteMcpSource:
    connection_id = str(row.get("id") or "").strip()
    endpoint_url = str(row.get("endpoint_url") or "").strip()
    if not connection_id or not endpoint_url:
        raise ValueError("saved MCP connection is missing id or endpoint URL")
    transport = str(row.get("transport") or "streamable_http").strip().lower().replace("-", "_")
    if transport == "streamablehttp":
        transport = "streamable_http"
    if transport not in TRANSPORTS:
        raise ValueError(f"unsupported saved MCP transport: {transport}")
    auth_type = str(row.get("auth_type") or "none").strip().lower()
    if auth_type not in AUTH_TYPES:
        raise ValueError(f"unsupported saved MCP auth type: {auth_type}")
    secret_config = row.get("secret_config") if isinstance(row.get("secret_config"), dict) else {}
    headers = _normalize_headers(secret_config.get("headers") or {})
    return RemoteMcpSource(
        name=_runtime_source_name(connection_id),
        display_name=str(row.get("name") or connection_id).strip(),
        connection_id=connection_id,
        url=endpoint_url,
        transport=transport,
        auth_type=auth_type,
        headers=tuple(headers.items()),
    )


def parse_curl_connection(command: str, *, name: str = "imported") -> dict[str, Any]:
    # Parse a bounded cURL request into a reusable MCP connection draft.
    try:
        tokens = shlex.split(command.strip())
    except ValueError as exc:
        raise ValueError("invalid cURL command") from exc
    if not tokens or tokens[0].lower() != "curl":
        raise ValueError("cURL import must start with curl")
    url = ""
    method = "POST"
    headers: dict[str, str] = {}
    body: str | None = None
    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token in {"-H", "--header"} and i + 1 < len(tokens):
            i += 1
            raw = tokens[i]
            if ":" not in raw:
                raise ValueError("cURL header must use Name: value")
            key, value = raw.split(":", 1)
            headers[key.strip()] = value.strip()
        elif token in {"-X", "--request"} and i + 1 < len(tokens):
            i += 1
            method = tokens[i].upper()
        elif token in {"-d", "--data", "--data-raw", "--data-binary"} and i + 1 < len(tokens):
            i += 1
            body = tokens[i]
        elif token in {"-u", "--user", "--cookie", "-b", "--cert", "--key"}:
            raise ValueError(f"unsupported credential-bearing cURL option: {token}")
        elif token.startswith(("http://", "https://")):
            url = token
        i += 1
    if not url:
        raise ValueError("cURL import requires an http(s) URL")
    headers = _normalize_headers(headers)
    auth_type = "headers"
    authorization = next((v for k, v in headers.items() if k.lower() == "authorization"), "")
    if authorization.lower().startswith("bearer "):
        auth_type = "bearer"
    elif any(k.lower() in {"x-api-key", "api-key", "x-api-token"} for k in headers):
        auth_type = "api_key"
    elif not headers:
        auth_type = "none"
    return {
        "name": name,
        "url": url,
        "transport": "streamable_http",
        "auth_type": auth_type,
        "headers": headers,
        "request_method": method,
        "request_body": body,
    }


async def probe_saved_connection(
    row: dict[str, Any],
    *,
    timeout_seconds: int = 15,
    validate_urls: bool = True,
) -> dict[str, Any]:
    """Perform a real MCP initialize/list-tools handshake for one saved connection."""
    source = _source_from_connection(row)
    if validate_urls:
        validate_public_http_url(source.url)

    provider = RemoteMcpToolProvider(
        sources=[source],
        validate_urls=validate_urls,
        connection_loader=lambda _user_id: [],
    )
    async with asyncio.timeout(max(3, min(int(timeout_seconds), 30))):
        tools = await provider._tools(source)

    preview = [
        {
            "ref": tool.ref,
            "name": tool.name,
            "description": tool.description[:240],
            "side_effecting": bool(tool.side_effecting),
            "requires_auth": bool(tool.requires_auth),
        }
        for tool in tools[:25]
    ]
    return {
        "ok": True,
        "source": source.public_dict(),
        "tool_count": len(tools),
        "tools": preview,
    }


def _side_effecting(tool: Any) -> bool:
    """Absent MCP readOnlyHint means mutation remains possible."""
    raw: dict[str, Any] = {}
    if hasattr(tool, "model_dump"):
        value = tool.model_dump(mode="json")
        if isinstance(value, dict):
            raw = value
    annotations = raw.get("annotations") if isinstance(raw.get("annotations"), dict) else {}
    read_only = annotations.get("readOnlyHint")
    if read_only is None:
        read_only = annotations.get("read_only_hint")
    return read_only is not True


class RemoteMcpToolProvider:
    """Expose global and authenticated user-owned remote MCP servers through the Tool Mesh."""

    name = "mcp"

    def __init__(
        self,
        sources: list[RemoteMcpSource] | None = None,
        *,
        cache_seconds: int = 60,
        validate_urls: bool = True,
        store: ControlStore | None = None,
        connection_loader: ConnectionLoader | None = None,
    ) -> None:
        self.sources = sources if sources is not None else self._sources_from_env()
        self.cache_seconds = max(15, cache_seconds)
        self.validate_urls = validate_urls
        self.store = store or ControlStore()
        self.connection_loader = connection_loader or self._load_saved_connections
        self._cache: dict[str, tuple[float, list[ToolDescriptor]]] = {}

    @staticmethod
    def _sources_from_env() -> list[RemoteMcpSource]:
        raw = os.getenv("INTERNET_HANDS_REMOTE_MCP_SOURCES", "").strip()
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("INTERNET_HANDS_REMOTE_MCP_SOURCES must be valid JSON") from exc
        if not isinstance(payload, list):
            raise TypeError("INTERNET_HANDS_REMOTE_MCP_SOURCES must be a JSON array")

        sources: list[RemoteMcpSource] = []
        names: set[str] = set()
        for item in payload:
            if not isinstance(item, dict) or not item.get("name") or not item.get("url"):
                continue
            source = _normalize_source(item)
            if source.name in names:
                raise ValueError(f"duplicate remote MCP source name: {source.name}")
            names.add(source.name)
            sources.append(source)
        return sources

    def _load_saved_connections(self, user_id: str) -> list[dict[str, Any]]:
        """Load private runtime connection material without exposing it through the control API."""
        self.store.ensure_schema()
        with self.store._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id,name,endpoint_url,transport,auth_type,secret_config
                FROM ih_connections
                WHERE user_id=%s AND kind='mcp' AND enabled=true
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    def _active_sources(self) -> list[RemoteMcpSource]:
        sources = list(self.sources)
        identity = current_auth.get()
        if identity is None:
            return sources
        saved = self.connection_loader(identity.user_id)
        known = {source.name for source in sources}
        for row in saved:
            source = _source_from_connection(row)
            if source.name in known:
                raise ValueError(f"duplicate remote MCP source id: {source.name}")
            known.add(source.name)
            sources.append(source)
        return sources

    async def status(self) -> dict[str, Any]:
        sources = self._active_sources()
        return {
            "configured": bool(sources),
            "searchable": bool(sources),
            "executable": bool(sources),
            "kind": "remote-mcp-catalog",
            "source_count": len(sources),
            "global_source_count": len(self.sources),
            "user_source_count": max(0, len(sources) - len(self.sources)),
            "sources": [source.public_dict() for source in sources],
            "authentication": "none, API key, bearer, custom headers, or OAuth-provided headers",
        }

    @asynccontextmanager
    async def _client(self, source: RemoteMcpSource):
        headers = dict(source.headers)
        if source.transport == "sse":
            async with Client(sse_client(source.url, headers=headers or None)) as client:
                yield client
            return
        if not headers:
            async with Client(source.url) as client:
                yield client
            return
        async with httpx2.AsyncClient(headers=headers) as http_client:
            transport = streamable_http_client(source.url, http_client=http_client)
            async with Client(transport) as client:
                yield client

    async def _tools(self, source: RemoteMcpSource) -> list[ToolDescriptor]:
        cached = self._cache.get(source.name)
        if cached and time.monotonic() - cached[0] < self.cache_seconds:
            return cached[1]
        if self.validate_urls:
            validate_public_http_url(source.url)

        descriptors: list[ToolDescriptor] = []
        async with self._client(source) as client:
            cursor: str | None = None
            while True:
                result = await client.list_tools(cursor=cursor)
                for tool in result.tools:
                    tool_name = str(tool.name)
                    input_schema = getattr(tool, "input_schema", None) or {}
                    output_schema = getattr(tool, "output_schema", None) or {}
                    descriptors.append(
                        ToolDescriptor(
                            ref=f"mcp:{source.name}::{tool_name}",
                            provider="mcp",
                            tool_id=f"{source.name}::{tool_name}",
                            name=str(getattr(tool, "title", None) or tool_name),
                            description=str(getattr(tool, "description", None) or ""),
                            input_schema=input_schema if isinstance(input_schema, dict) else {},
                            output_schema=output_schema if isinstance(output_schema, dict) else {},
                            tags=["mcp", source.display_name or source.name],
                            requires_auth=source.requires_auth,
                            side_effecting=_side_effecting(tool),
                            metadata={
                                "source": source.name,
                                "source_name": source.display_name or source.name,
                                "connection_id": source.connection_id,
                                "endpoint": source.url,
                                "untrusted_external": True,
                                "transport": source.transport,
                                "auth_type": source.auth_type,
                            },
                        )
                    )
                cursor = getattr(result, "next_cursor", None)
                if not cursor:
                    break
        self._cache[source.name] = (time.monotonic(), descriptors)
        return descriptors

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        words = [word for word in re.split(r"\W+", query.casefold()) if word]
        ranked: list[tuple[int, ToolDescriptor]] = []
        for source in self._active_sources():
            try:
                tools = await self._tools(source)
            except Exception:  # noqa: BLE001 - one remote MCP must not hide other sources
                tools = []
            for tool in tools:
                haystack = " ".join(
                    [tool.tool_id, tool.name, tool.description, *tool.tags]
                ).casefold()
                score = sum(
                    5 if word in tool.name.casefold() else 1
                    for word in words
                    if word in haystack
                )
                if score or not words:
                    ranked.append((score, tool))
        ranked.sort(key=lambda row: (-row[0], row[1].ref))
        return [tool for _, tool in ranked[: max(1, min(limit, 50))]]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        source_name, separator, remote_tool = tool_id.partition("::")
        if not separator:
            raise ValueError("remote MCP tool id must use source::tool")
        source = next((item for item in self._active_sources() if item.name == source_name), None)
        if source is None:
            raise ValueError(f"unknown remote MCP source: {source_name}")
        for tool in await self._tools(source):
            if tool.tool_id == f"{source_name}::{remote_tool}":
                return tool
        raise ValueError(f"unknown remote MCP tool: {tool_id}")

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
        del account, wait_seconds, timeout_seconds, options
        source_name, separator, remote_tool = tool_id.partition("::")
        if not separator:
            raise ValueError("remote MCP tool id must use source::tool")
        source = next((item for item in self._active_sources() if item.name == source_name), None)
        if source is None:
            raise ValueError(f"unknown remote MCP source: {source_name}")
        if self.validate_urls:
            validate_public_http_url(source.url)

        async with self._client(source) as client:
            result = await client.call_tool(remote_tool, arguments)
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            data: Any = structured
        else:
            data = []
            for block in getattr(result, "content", []) or []:
                if hasattr(block, "model_dump"):
                    data.append(block.model_dump(mode="json"))
                else:
                    data.append(str(block))
        is_error = bool(getattr(result, "is_error", False))
        return {
            "status": "failed" if is_error else "completed",
            "job_id": None,
            "result_id": None,
            "data": data,
            "error": "remote MCP tool returned an error" if is_error else None,
            "metadata": {
                "source": source_name,
                "source_name": source.display_name or source.name,
                "connection_id": source.connection_id,
                "remote_tool": remote_tool,
                "untrusted_external": True,
            },
        }

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        del job_id, wait_seconds
        raise NotImplementedError("remote MCP job handles are provider-specific")

    async def result_page(
        self, result_id: str, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        del result_id, offset, limit
        raise NotImplementedError("remote MCP result stores are provider-specific")


def build_remote_mcp_provider() -> RemoteMcpToolProvider:
    return RemoteMcpToolProvider()
