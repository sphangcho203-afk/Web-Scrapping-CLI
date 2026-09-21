from __future__ import annotations

import asyncio
import os
from typing import Any

from .crawler import crawl
from .fetcher import extract_links, fetch_url
from .tool_mesh import ToolDescriptor
from .web_search import SearchKind, brave_search


class NativeWebToolProvider:
    """First-party public-web fallback provider with no marketplace dependency."""

    name = "nativeweb"

    async def status(self) -> dict[str, Any]:
        return {
            "configured": True,
            "searchable": True,
            "executable": True,
            "search_configured": bool(os.getenv("BRAVE_SEARCH_API_KEY")),
            "network": "public-http-only",
            "fallback": True,
        }

    def _descriptors(self) -> dict[str, ToolDescriptor]:
        return {
            "fetch": ToolDescriptor(
                ref="nativeweb:fetch",
                provider=self.name,
                tool_id="fetch",
                name="Native public page fetch",
                description="Fetch one public HTTP(S) URL with SSRF-safe redirects and bounded body size.",
                input_schema={
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {"type": "string"},
                        "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 60},
                        "max_bytes": {"type": "integer", "minimum": 32000, "maximum": 8000000},
                    },
                },
                tags=["web", "fetch", "native", "fallback"],
                requires_auth=False,
                side_effecting=False,
            ),
            "search": ToolDescriptor(
                ref="nativeweb:search",
                provider=self.name,
                tool_id="search",
                name="Native Brave web search",
                description="Search the public web through the configured Brave Search API.",
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string"},
                        "count": {"type": "integer", "minimum": 1, "maximum": 20},
                        "country": {"type": "string"},
                        "language": {"type": "string"},
                        "freshness": {"type": "string"},
                    },
                },
                tags=["web", "search", "brave", "native", "fallback"],
                requires_auth=True,
                side_effecting=False,
            ),
            "map": ToolDescriptor(
                ref="nativeweb:map",
                provider=self.name,
                tool_id="map",
                name="Native site link map",
                description="Fetch a public page and return bounded same-page discovered HTTP(S) links.",
                input_schema={
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                    },
                },
                tags=["web", "map", "links", "native", "fallback"],
                requires_auth=False,
                side_effecting=False,
            ),
            "crawl": ToolDescriptor(
                ref="nativeweb:crawl",
                provider=self.name,
                tool_id="crawl",
                name="Native bounded site crawl",
                description="Crawl a public site with robots, SSRF, depth, page, time, and concurrency bounds.",
                input_schema={
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                        "max_pages": {"type": "integer", "minimum": 1, "maximum": 500},
                        "max_depth": {"type": "integer", "minimum": 0, "maximum": 50},
                        "concurrency": {"type": "integer", "minimum": 1, "maximum": 12},
                        "max_seconds": {"type": "number", "minimum": 1, "maximum": 600},
                        "include_paths": {"type": "array", "items": {"type": "string"}},
                        "exclude_paths": {"type": "array", "items": {"type": "string"}},
                        "include_subdomains": {"type": "boolean"},
                        "preserve_query": {"type": "boolean"},
                    },
                },
                tags=["web", "crawl", "native", "fallback"],
                requires_auth=False,
                side_effecting=False,
            ),
            "batch-fetch": ToolDescriptor(
                ref="nativeweb:batch-fetch",
                provider=self.name,
                tool_id="batch-fetch",
                name="Native bounded batch fetch",
                description="Fetch up to 20 public URLs concurrently with per-item failure isolation.",
                input_schema={
                    "type": "object",
                    "required": ["urls"],
                    "properties": {
                        "urls": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 20,
                            "items": {"type": "string"},
                        },
                        "concurrency": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                },
                tags=["web", "batch", "fetch", "native", "fallback"],
                requires_auth=False,
                side_effecting=False,
            ),
        }

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        words = [word for word in query.casefold().split() if word]
        rows: list[tuple[int, ToolDescriptor]] = []
        for descriptor in self._descriptors().values():
            haystack = " ".join(
                [descriptor.tool_id, descriptor.name, descriptor.description, *descriptor.tags]
            ).casefold()
            score = sum(1 for word in words if word in haystack)
            if score or not words:
                rows.append((score, descriptor))
        rows.sort(key=lambda row: (-row[0], row[1].tool_id))
        return [descriptor for _, descriptor in rows[: max(1, min(limit, 10))]]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        try:
            return self._descriptors()[tool_id]
        except KeyError as exc:
            raise ValueError(f"unknown native web tool: {tool_id}") from exc

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
        await self.describe(tool_id)

        if tool_id == "fetch":
            result = await fetch_url(
                str(arguments["url"]),
                timeout=min(float(arguments.get("timeout_seconds", timeout_seconds)), 60.0),
                max_bytes=int(arguments.get("max_bytes", 2_000_000)),
                include_body=True,
            )
            return {"status": "completed", "data": result.model_dump(mode="json")}

        if tool_id == "search":
            result = await brave_search(
                str(arguments["query"]),
                kind=SearchKind.WEB,
                count=int(arguments.get("count", arguments.get("limit", 10))),
                country=arguments.get("country"),
                language=arguments.get("language"),
                freshness=arguments.get("freshness"),
            )
            return {"status": "completed", "data": result}

        if tool_id == "map":
            result = await fetch_url(
                str(arguments["url"]),
                timeout=min(float(arguments.get("timeout_seconds", timeout_seconds)), 60.0),
                max_bytes=2_000_000,
                include_body=True,
            )
            links = extract_links(result).links
            limit = max(1, min(int(arguments.get("limit", 250)), 1000))
            return {
                "status": "completed",
                "data": {
                    "url": result.final_url,
                    "links": links[:limit],
                    "total_links": len(links),
                    "truncated": len(links) > limit,
                },
            }

        if tool_id == "crawl":
            max_pages = int(arguments.get("max_pages", arguments.get("limit", 25)))
            result = await crawl(
                str(arguments["url"]),
                max_pages=max_pages,
                max_depth=int(arguments.get("max_depth", 20)),
                concurrency=int(arguments.get("concurrency", 2)),
                max_seconds=min(float(arguments.get("max_seconds", timeout_seconds)), 600.0),
                include_paths=arguments.get("include_paths"),
                exclude_paths=arguments.get("exclude_paths"),
                include_subdomains=bool(arguments.get("include_subdomains", False)),
                preserve_query=bool(arguments.get("preserve_query", True)),
            )
            return {"status": "completed", "data": result.model_dump(mode="json")}

        if tool_id == "batch-fetch":
            raw_urls = arguments.get("urls") or []
            if not isinstance(raw_urls, list) or not raw_urls or len(raw_urls) > 20:
                raise ValueError("urls must contain between 1 and 20 public URLs")
            concurrency = max(1, min(int(arguments.get("concurrency", 5)), 10))
            semaphore = asyncio.Semaphore(concurrency)

            async def one(index: int, url: object) -> dict[str, Any]:
                async with semaphore:
                    try:
                        result = await fetch_url(
                            str(url),
                            timeout=min(float(timeout_seconds), 60.0),
                            max_bytes=2_000_000,
                            include_body=True,
                        )
                        return {
                            "index": index,
                            "status": "completed",
                            "data": result.model_dump(mode="json"),
                        }
                    except Exception as exc:  # noqa: BLE001 - batch item isolation boundary
                        return {
                            "index": index,
                            "status": "failed",
                            "error": f"{type(exc).__name__}: {exc}",
                        }

            items = await asyncio.gather(*(one(i, url) for i, url in enumerate(raw_urls)))
            return {"status": "completed", "data": {"results": items}}

        raise ValueError(f"unsupported native web tool: {tool_id}")

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        del job_id, wait_seconds
        raise ValueError("native web operations complete inline and do not create jobs")

    async def result_page(
        self,
        result_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        del result_id, offset, limit
        raise ValueError("native web operations return bounded inline results")
