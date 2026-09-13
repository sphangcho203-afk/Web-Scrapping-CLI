from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from mcp import Client

from .policy import validate_public_http_url
from .tool_mesh import ToolDescriptor


@dataclass(frozen=True, slots=True)
class RemoteMcpSource:
    name: str
    url: str


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
    """Expose configured public remote MCP servers through the Tool Mesh."""

    name = "mcp"

    def __init__(
        self,
        sources: list[RemoteMcpSource] | None = None,
        *,
        cache_seconds: int = 60,
        validate_urls: bool = True,
    ) -> None:
        self.sources = sources if sources is not None else self._sources_from_env()
        self.cache_seconds = max(15, cache_seconds)
        self.validate_urls = validate_urls
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
            name = str(item["name"]).strip().lower()
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", name):
                raise ValueError(f"invalid remote MCP source name: {name}")
            if name in names:
                raise ValueError(f"duplicate remote MCP source name: {name}")
            names.add(name)
            sources.append(RemoteMcpSource(name=name, url=str(item["url"])))
        return sources

    async def status(self) -> dict[str, Any]:
        return {
            "configured": bool(self.sources),
            "searchable": bool(self.sources),
            "executable": bool(self.sources),
            "kind": "remote-mcp-catalog",
            "source_count": len(self.sources),
            "sources": [{"name": source.name, "url": source.url} for source in self.sources],
            "authentication": "public endpoints only in v0.5",
        }

    async def _tools(self, source: RemoteMcpSource) -> list[ToolDescriptor]:
        cached = self._cache.get(source.name)
        if cached and time.monotonic() - cached[0] < self.cache_seconds:
            return cached[1]
        if self.validate_urls:
            validate_public_http_url(source.url)

        descriptors: list[ToolDescriptor] = []
        async with Client(source.url) as client:
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
                            tags=["mcp", source.name],
                            requires_auth=False,
                            side_effecting=_side_effecting(tool),
                            metadata={
                                "source": source.name,
                                "endpoint": source.url,
                                "untrusted_external": True,
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
        for source in self.sources:
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
        source = next((item for item in self.sources if item.name == source_name), None)
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
        source = next((item for item in self.sources if item.name == source_name), None)
        if source is None:
            raise ValueError(f"unknown remote MCP source: {source_name}")
        if self.validate_urls:
            validate_public_http_url(source.url)

        async with Client(source.url) as client:
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
