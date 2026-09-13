from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlsplit

import httpx

from .openapi import _load_document, _servers
from .policy import validate_public_http_url
from .tool_mesh import ToolDescriptor


_SAFE_METHODS = {"GET", "HEAD"}
_BLOCKED_HEADER_ARGS = {"authorization", "cookie", "proxy-authorization", "x-api-key"}


@dataclass(frozen=True, slots=True)
class HttpToolSpec:
    tool_id: str
    name: str
    description: str
    method: str
    base_url: str
    path: str
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    requires_auth: bool = False
    host_header: str | None = None
    auth_env: str | None = None
    auth_header: str | None = None
    side_effecting: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def input_schema(self) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for name, spec in self.parameters.items():
            schema = dict(spec.get("schema") or {})
            if not schema:
                schema = {"type": "string"}
            if spec.get("description"):
                schema["description"] = spec["description"]
            properties[name] = schema
            if spec.get("required"):
                required.append(name)
        result: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            result["required"] = required
        return result


class ManifestHttpProvider:
    """Read-only HTTP tools defined by curated manifests; credentials remain server-side."""

    def __init__(
        self,
        name: str,
        tools: list[HttpToolSpec],
        *,
        client: httpx.AsyncClient | None = None,
        max_response_bytes: int = 2_000_000,
        validate_urls: bool = True,
    ) -> None:
        self.name = name
        self.tools = {tool.tool_id: tool for tool in tools}
        self.client = client
        self.max_response_bytes = max_response_bytes
        self.validate_urls = validate_urls

    async def status(self) -> dict[str, Any]:
        configured = 0
        for tool in self.tools.values():
            if not tool.auth_env or os.getenv(tool.auth_env, "").strip():
                configured += 1
        return {
            "configured": configured > 0,
            "searchable": True,
            "executable": configured > 0,
            "kind": "manifest-http-catalog",
            "tool_count": len(self.tools),
            "configured_tools": configured,
        }

    def _descriptor(self, tool: HttpToolSpec) -> ToolDescriptor:
        return ToolDescriptor(
            ref=f"{self.name}:{tool.tool_id}",
            provider=self.name,
            tool_id=tool.tool_id,
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema(),
            output_schema={},
            tags=list(tool.tags),
            requires_auth=tool.requires_auth,
            side_effecting=tool.side_effecting,
            metadata={
                "method": tool.method,
                "base_url": tool.base_url,
                "path": tool.path,
                **tool.metadata,
            },
        )

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        words = [word for word in re.split(r"\W+", query.lower()) if word]
        ranked: list[tuple[int, HttpToolSpec]] = []
        for tool in self.tools.values():
            haystack = " ".join(
                [tool.tool_id, tool.name, tool.description, *tool.tags]
            ).lower()
            score = sum(4 if word in tool.name.lower() else 1 for word in words if word in haystack)
            if score or not words:
                ranked.append((score, tool))
        ranked.sort(key=lambda row: (-row[0], row[1].tool_id))
        return [self._descriptor(tool) for _, tool in ranked[: max(1, min(limit, 50))]]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        try:
            return self._descriptor(self.tools[tool_id])
        except KeyError as exc:
            raise ValueError(f"unknown {self.name} tool: {tool_id}") from exc

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
        del account, wait_seconds, options
        try:
            tool = self.tools[tool_id]
        except KeyError as exc:
            raise ValueError(f"unknown {self.name} tool: {tool_id}") from exc
        method = tool.method.upper()
        if method not in _SAFE_METHODS or tool.side_effecting:
            raise PermissionError("manifest HTTP provider only executes read-only GET/HEAD tools")

        missing = [
            name
            for name, spec in tool.parameters.items()
            if spec.get("required") and name not in arguments
        ]
        if missing:
            raise ValueError(f"missing required arguments: {', '.join(missing)}")

        path = tool.path
        query: dict[str, Any] = {}
        headers = {"Accept": "application/json"}
        for name, value in arguments.items():
            spec = tool.parameters.get(name)
            if spec is None or value is None:
                continue
            location = str(spec.get("in") or "query")
            if location == "path":
                path = path.replace("{" + name + "}", quote(str(value), safe=""))
            elif location == "query":
                query[name] = value
            elif location == "header" and name.lower() not in _BLOCKED_HEADER_ARGS:
                headers[name] = str(value)

        if tool.auth_env:
            secret = os.getenv(tool.auth_env, "").strip()
            if not secret:
                raise RuntimeError(f"{tool.auth_env} is required for {self.name}:{tool_id}")
            headers[tool.auth_header or "Authorization"] = secret
        if tool.host_header:
            headers["X-RapidAPI-Host"] = tool.host_header

        base = tool.base_url.rstrip("/") + "/"
        url = urljoin(base, path.lstrip("/"))
        if self.validate_urls:
            validate_public_http_url(url)
        response = await self._request(
            method,
            url,
            params=query,
            headers=headers,
            timeout=max(1.0, min(float(timeout_seconds), 120.0)),
        )
        raw = response.content
        if len(raw) > self.max_response_bytes:
            data: Any = {
                "truncated": True,
                "bytes": len(raw),
                "max_bytes": self.max_response_bytes,
                "preview": raw[: self.max_response_bytes].decode("utf-8", errors="replace"),
            }
        else:
            try:
                data = response.json()
            except ValueError:
                data = response.text
        return {
            "status": "completed",
            "job_id": None,
            "result_id": None,
            "data": data,
            "metadata": {
                "http_status": response.status_code,
                "method": method,
                "host": urlsplit(url).hostname,
            },
        }

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self.client is not None:
            response = await self.client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        async with httpx.AsyncClient(follow_redirects=False) as client:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        del job_id, wait_seconds
        raise NotImplementedError(f"{self.name} tools return results inline")

    async def result_page(
        self, result_id: str, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        del result_id, offset, limit
        raise NotImplementedError(f"{self.name} tools return results inline")


def _load_extra_manifest(env_name: str) -> list[HttpToolSpec]:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{env_name} must be valid JSON") from exc
    if not isinstance(payload, list):
        raise RuntimeError(f"{env_name} must contain a JSON array")
    tools: list[HttpToolSpec] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        method = str(item.get("method") or "GET").upper()
        if method not in _SAFE_METHODS:
            continue
        tools.append(
            HttpToolSpec(
                tool_id=str(item["tool_id"]),
                name=str(item.get("name") or item["tool_id"]),
                description=str(item.get("description") or ""),
                method=method,
                base_url=str(item["base_url"]),
                path=str(item.get("path") or "/"),
                parameters=dict(item.get("parameters") or {}),
                tags=tuple(str(value) for value in item.get("tags") or []),
                requires_auth=bool(item.get("requires_auth", False)),
                host_header=item.get("host_header"),
                auth_env=item.get("auth_env"),
                auth_header=item.get("auth_header"),
                metadata=dict(item.get("metadata") or {}),
            )
        )
    return tools


def build_rapidapi_provider() -> ManifestHttpProvider:
    tools = [
        HttpToolSpec(
            tool_id="mlbb-player-lookup",
            name="MLBB player lookup",
            description=(
                "Look up public/community Mobile Legends player profile information by player id "
                "and optional zone id through a RapidAPI provider."
            ),
            method="GET",
            base_url="https://mobile-legends-user-info-lookup.p.rapidapi.com",
            path="/lookup",
            parameters={
                "id": {
                    "in": "query",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "Mobile Legends player ID",
                },
                "zone": {
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": "Mobile Legends zone/server ID",
                },
            },
            tags=("mlbb", "mobile-legends", "player", "profile", "rapidapi"),
            requires_auth=True,
            host_header="mobile-legends-user-info-lookup.p.rapidapi.com",
            auth_env="RAPIDAPI_KEY",
            auth_header="X-RapidAPI-Key",
            metadata={"source": "rapidapi", "unofficial": True},
        )
    ]
    tools.extend(_load_extra_manifest("INTERNET_HANDS_RAPIDAPI_TOOLS"))
    return ManifestHttpProvider("rapidapi", tools)


def build_publicapi_provider() -> ManifestHttpProvider:
    tools = [
        HttpToolSpec(
            tool_id="mlbb-nickname-lookup",
            name="MLBB nickname lookup",
            description="Read an MLBB nickname from a public community lookup endpoint.",
            method="GET",
            base_url="https://api.isan.eu.org",
            path="/nickname/ml",
            parameters={
                "id": {
                    "in": "query",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "Mobile Legends player ID",
                },
                "server": {
                    "in": "query",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "Mobile Legends server/zone ID",
                },
            },
            tags=("mlbb", "mobile-legends", "nickname", "public-api"),
            requires_auth=False,
            metadata={"unofficial": True, "read_only": True},
        )
    ]
    tools.extend(_load_extra_manifest("INTERNET_HANDS_PUBLIC_API_TOOLS"))
    return ManifestHttpProvider("publicapi", tools)


@dataclass(slots=True)
class _OpenApiSource:
    name: str
    spec_url: str
    headers_env: str | None = None


class OpenApiToolProvider:
    """Dynamically turns configured public OpenAPI GET/HEAD operations into mesh tools."""

    name = "openapi"

    def __init__(
        self,
        sources: list[_OpenApiSource] | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        cache_seconds: int = 600,
        validate_urls: bool = True,
    ) -> None:
        self.sources = sources or self._default_sources()
        self.client = client
        self.cache_seconds = max(30, cache_seconds)
        self.validate_urls = validate_urls
        self._cache: dict[str, tuple[float, dict[str, Any], str]] = {}

    @staticmethod
    def _default_sources() -> list[_OpenApiSource]:
        sources = [
            _OpenApiSource("rone-mlbb", "https://arena.rone.dev/api/openapi.json"),
        ]
        raw = os.getenv("INTERNET_HANDS_OPENAPI_SOURCES", "").strip()
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError("INTERNET_HANDS_OPENAPI_SOURCES must be valid JSON") from exc
            if not isinstance(payload, list):
                raise RuntimeError("INTERNET_HANDS_OPENAPI_SOURCES must be a JSON array")
            for item in payload:
                if isinstance(item, dict) and item.get("name") and item.get("url"):
                    sources.append(
                        _OpenApiSource(
                            str(item["name"]),
                            str(item["url"]),
                            str(item["headers_env"]) if item.get("headers_env") else None,
                        )
                    )
        return sources

    async def status(self) -> dict[str, Any]:
        return {
            "configured": bool(self.sources),
            "searchable": bool(self.sources),
            "executable": bool(self.sources),
            "kind": "dynamic-openapi-readonly",
            "source_count": len(self.sources),
            "sources": [{"name": source.name, "url": source.spec_url} for source in self.sources],
            "methods": sorted(_SAFE_METHODS),
        }

    async def _load(self, source: _OpenApiSource) -> tuple[dict[str, Any], str]:
        cached = self._cache.get(source.name)
        if cached and time.monotonic() - cached[0] < self.cache_seconds:
            return cached[1], cached[2]
        if self.validate_urls:
            validate_public_http_url(source.spec_url)
        headers = {"Accept": "application/json, application/yaml, text/yaml"}
        if source.headers_env:
            raw = os.getenv(source.headers_env, "").strip()
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    headers.update({str(k): str(v) for k, v in parsed.items()})
        response = await self._request("GET", source.spec_url, headers=headers, timeout=30.0)
        spec = _load_document(response.text)
        final_url = str(response.url)
        self._cache[source.name] = (time.monotonic(), spec, final_url)
        return spec, final_url

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self.client is not None:
            response = await self.client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        async with httpx.AsyncClient(follow_redirects=False) as client:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response

    @staticmethod
    def _operation_id(method: str, path: str, operation: dict[str, Any]) -> str:
        operation_id = str(operation.get("operationId") or "").strip()
        if operation_id:
            return operation_id
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", path).strip("_") or "root"
        return f"{method.lower()}_{slug}"

    @staticmethod
    def _input_schema(path_item: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
        parameters: list[Any] = []
        for value in (path_item.get("parameters"), operation.get("parameters")):
            if isinstance(value, list):
                parameters.extend(value)
        properties: dict[str, Any] = {}
        required: list[str] = []
        for parameter in parameters:
            if not isinstance(parameter, dict):
                continue
            name = parameter.get("name")
            location = parameter.get("in")
            if not isinstance(name, str) or location not in {"path", "query", "header"}:
                continue
            if location == "header" and name.lower() in _BLOCKED_HEADER_ARGS:
                continue
            schema = parameter.get("schema") if isinstance(parameter.get("schema"), dict) else {}
            item = dict(schema)
            if not item:
                item["type"] = "string"
            if parameter.get("description"):
                item["description"] = parameter["description"]
            item["x-in"] = location
            properties[name] = item
            if parameter.get("required"):
                required.append(name)
        result: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            result["required"] = required
        return result

    async def _operations(self, source: _OpenApiSource) -> list[ToolDescriptor]:
        spec, final_url = await self._load(source)
        paths = spec.get("paths")
        if not isinstance(paths, dict):
            return []
        servers = _servers(spec, final_url)
        server = servers[0] if servers else urljoin(final_url, "/")
        descriptors: list[ToolDescriptor] = []
        for path, path_item in paths.items():
            if not isinstance(path, str) or not isinstance(path_item, dict):
                continue
            for method in ("get", "head"):
                operation = path_item.get(method)
                if not isinstance(operation, dict):
                    continue
                operation_id = self._operation_id(method, path, operation)
                tool_id = f"{source.name}::{operation_id}"
                tags = [str(value) for value in operation.get("tags") or []]
                descriptors.append(
                    ToolDescriptor(
                        ref=f"openapi:{tool_id}",
                        provider="openapi",
                        tool_id=tool_id,
                        name=str(operation.get("summary") or operation_id),
                        description=str(operation.get("description") or ""),
                        input_schema=self._input_schema(path_item, operation),
                        output_schema={},
                        tags=[source.name, *tags],
                        requires_auth=bool(operation.get("security") or spec.get("security")),
                        side_effecting=False,
                        metadata={
                            "source": source.name,
                            "spec_url": source.spec_url,
                            "server": server,
                            "method": method.upper(),
                            "path": path,
                            "operation_id": operation_id,
                        },
                    )
                )
        return descriptors

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        words = [word for word in re.split(r"\W+", query.lower()) if word]
        rows: list[tuple[int, ToolDescriptor]] = []
        for source in self.sources:
            try:
                descriptors = await self._operations(source)
            except Exception:
                continue
            for descriptor in descriptors:
                haystack = " ".join(
                    [
                        descriptor.tool_id,
                        descriptor.name,
                        descriptor.description,
                        *descriptor.tags,
                        str(descriptor.metadata.get("path") or ""),
                    ]
                ).lower()
                score = sum(5 if word in descriptor.name.lower() else 1 for word in words if word in haystack)
                if score or not words:
                    rows.append((score, descriptor))
        rows.sort(key=lambda row: (-row[0], row[1].ref))
        return [descriptor for _, descriptor in rows[: max(1, min(limit, 50))]]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        source_name, separator, operation_id = tool_id.partition("::")
        if not separator:
            raise ValueError("OpenAPI tool id must use source::operation")
        source = next((item for item in self.sources if item.name == source_name), None)
        if source is None:
            raise ValueError(f"unknown OpenAPI source: {source_name}")
        for descriptor in await self._operations(source):
            if descriptor.metadata.get("operation_id") == operation_id:
                return descriptor
        raise ValueError(f"unknown OpenAPI operation: {tool_id}")

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
        del account, wait_seconds, options
        descriptor = await self.describe(tool_id)
        method = str(descriptor.metadata["method"])
        server = str(descriptor.metadata["server"])
        path = str(descriptor.metadata["path"])
        properties = descriptor.input_schema.get("properties") or {}
        required = set(descriptor.input_schema.get("required") or [])
        missing = [name for name in required if name not in arguments]
        if missing:
            raise ValueError(f"missing required arguments: {', '.join(sorted(missing))}")
        query: dict[str, Any] = {}
        headers = {"Accept": "application/json"}
        for name, value in arguments.items():
            if name not in properties or value is None:
                continue
            location = properties[name].get("x-in", "query")
            if location == "path":
                path = path.replace("{" + name + "}", quote(str(value), safe=""))
            elif location == "query":
                query[name] = value
            elif location == "header" and name.lower() not in _BLOCKED_HEADER_ARGS:
                headers[name] = str(value)
        url = urljoin(server.rstrip("/") + "/", path.lstrip("/"))
        if self.validate_urls:
            validate_public_http_url(url)
        response = await self._request(
            method,
            url,
            params=query,
            headers=headers,
            timeout=max(1.0, min(float(timeout_seconds), 120.0)),
        )
        try:
            data: Any = response.json()
        except ValueError:
            data = response.text
        return {
            "status": "completed",
            "job_id": None,
            "result_id": None,
            "data": data,
            "metadata": {
                "http_status": response.status_code,
                "source": descriptor.metadata.get("source"),
                "operation_id": descriptor.metadata.get("operation_id"),
            },
        }

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        del job_id, wait_seconds
        raise NotImplementedError("OpenAPI read operations return results inline")

    async def result_page(
        self, result_id: str, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        del result_id, offset, limit
        raise NotImplementedError("OpenAPI read operations return results inline")


def build_catalog_providers() -> list[ManifestHttpProvider | OpenApiToolProvider]:
    return [build_rapidapi_provider(), build_publicapi_provider(), OpenApiToolProvider()]
