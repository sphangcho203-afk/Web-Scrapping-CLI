from __future__ import annotations

import os
import re
from typing import Any

import httpx

from .execution_meter import record_usage
from .policy import validate_public_http_url
from .tool_mesh import ToolDescriptor


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        result["required"] = required
    return result


def _str(description: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {"type": "string"}
    if description:
        result["description"] = description
    return result


def _string_array(*, max_items: int = 50) -> dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "string"},
        "maxItems": max_items,
    }


class _JsonPostProvider:
    name: str
    base_url: str

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.client = client
        self._tools = self._build_tools()

    def _build_tools(self) -> dict[str, ToolDescriptor]:
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    async def status(self) -> dict[str, Any]:
        return {
            "configured": bool(self.api_key),
            "searchable": True,
            "executable": bool(self.api_key),
            "kind": "documented-web-intelligence-api",
            "tool_count": len(self._tools),
            "tools": sorted(self._tools),
        }

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        words = [word for word in re.split(r"\W+", query.casefold()) if word]
        rows: list[tuple[int, ToolDescriptor]] = []
        for descriptor in self._tools.values():
            haystack = " ".join(
                [descriptor.tool_id, descriptor.name, descriptor.description, *descriptor.tags]
            ).casefold()
            score = sum(
                4 if word in descriptor.name.casefold() else 1
                for word in words
                if word in haystack
            )
            if score or not words:
                rows.append((score, descriptor))
        rows.sort(key=lambda row: (-row[0], row[1].tool_id))
        return [item for _, item in rows[: max(1, min(int(limit), 50))]]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise ValueError(f"unknown {self.name} tool: {tool_id}") from exc

    async def _request(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError(f"{self.name.upper()} API key is not configured")
        url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        validate_public_http_url(url)
        timeout = max(1.0, min(float(timeout_seconds), 180.0))
        if self.client is not None:
            response = await self.client.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
        else:
            async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
                response = await client.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise TypeError(f"{self.name} returned a non-object response")
        return data

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        del job_id, wait_seconds
        raise ValueError(f"{self.name} tools complete inline")

    async def result_page(
        self,
        result_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        del result_id, offset, limit
        raise ValueError(f"{self.name} tools return bounded inline results")


class TavilyToolProvider(_JsonPostProvider):
    name = "tavily"
    base_url = "https://api.tavily.com"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            api_key if api_key is not None else os.getenv("TAVILY_API_KEY", "").strip(),
            client=client,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _build_tools(self) -> dict[str, ToolDescriptor]:
        common_map = {
            "url": _str("Public HTTP(S) root URL"),
            "instructions": _str("Natural-language crawl/map guidance"),
            "max_depth": {"type": "integer", "minimum": 1, "maximum": 5},
            "max_breadth": {"type": "integer", "minimum": 1, "maximum": 100},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "select_paths": _string_array(max_items=50),
            "select_domains": _string_array(max_items=50),
            "exclude_paths": _string_array(max_items=50),
            "exclude_domains": _string_array(max_items=50),
            "allow_external": {"type": "boolean"},
            "timeout": {"type": "number", "minimum": 10, "maximum": 150},
            "include_usage": {"type": "boolean"},
        }
        return {
            "search": ToolDescriptor(
                ref="tavily:search",
                provider=self.name,
                tool_id="search",
                name="Tavily web search",
                description="Agent-oriented web search with ranked extracted content.",
                input_schema=_schema(
                    {
                        "query": _str("Search query"),
                        "search_depth": {"type": "string", "enum": ["basic", "advanced"]},
                        "chunks_per_source": {"type": "integer", "minimum": 1, "maximum": 3},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
                        "topic": {"type": "string", "enum": ["general", "news"]},
                        "time_range": {"type": "string"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                        "include_answer": {"type": "boolean"},
                        "include_raw_content": {"type": "boolean"},
                        "include_images": {"type": "boolean"},
                        "include_image_descriptions": {"type": "boolean"},
                        "include_favicon": {"type": "boolean"},
                        "include_domains": _string_array(max_items=50),
                        "exclude_domains": _string_array(max_items=50),
                        "country": {"type": "string"},
                        "auto_parameters": {"type": "boolean"},
                        "exact_match": {"type": "boolean"},
                        "safe_search": {"type": "boolean"},
                        "include_usage": {"type": "boolean"},
                    },
                    ["query"],
                ),
                tags=["web", "search", "research", "tavily", "agent"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/search", "official": True},
            ),
            "extract": ToolDescriptor(
                ref="tavily:extract",
                provider=self.name,
                tool_id="extract",
                name="Tavily URL extract",
                description="Extract clean content from up to 20 public URLs.",
                input_schema=_schema(
                    {
                        "urls": {
                            "type": "array",
                            "items": {"type": "string", "format": "uri"},
                            "minItems": 1,
                            "maxItems": 20,
                        },
                        "query": {"type": "string"},
                        "chunks_per_source": {"type": "integer", "minimum": 1, "maximum": 3},
                        "extract_depth": {"type": "string", "enum": ["basic", "advanced"]},
                        "include_images": {"type": "boolean"},
                        "include_favicon": {"type": "boolean"},
                        "format": {"type": "string", "enum": ["markdown", "text"]},
                        "timeout": {"type": "number", "minimum": 5, "maximum": 120},
                        "include_usage": {"type": "boolean"},
                    },
                    ["urls"],
                ),
                tags=["web", "extract", "content", "tavily"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/extract", "official": True},
            ),
            "crawl": ToolDescriptor(
                ref="tavily:crawl",
                provider=self.name,
                tool_id="crawl",
                name="Tavily graph crawl",
                description="Bounded graph traversal with extraction and guided discovery.",
                input_schema=_schema(
                    {
                        **common_map,
                        "chunks_per_source": {"type": "integer", "minimum": 1, "maximum": 3},
                        "include_images": {"type": "boolean"},
                        "extract_depth": {"type": "string", "enum": ["basic", "advanced"]},
                        "format": {"type": "string", "enum": ["markdown", "text"]},
                        "include_favicon": {"type": "boolean"},
                    },
                    ["url"],
                ),
                tags=["web", "crawl", "graph", "extract", "tavily"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/crawl", "official": True},
            ),
            "map": ToolDescriptor(
                ref="tavily:map",
                provider=self.name,
                tool_id="map",
                name="Tavily site map",
                description="Bounded graph-based public site URL discovery.",
                input_schema=_schema(common_map, ["url"]),
                tags=["web", "map", "discovery", "links", "tavily"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/map", "official": True},
            ),
        }

    @staticmethod
    def _validate_urls(payload: dict[str, Any]) -> None:
        values: list[str] = []
        if isinstance(payload.get("url"), str):
            values.append(payload["url"])
        if isinstance(payload.get("urls"), list):
            values.extend(str(value) for value in payload["urls"] if isinstance(value, str))
        for value in values:
            validate_public_http_url(value)

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
        allowed = set((descriptor.input_schema.get("properties") or {}).keys())
        payload = {key: value for key, value in arguments.items() if key in allowed and value is not None}
        required = descriptor.input_schema.get("required") or []
        missing = [key for key in required if key not in payload]
        if missing:
            raise ValueError(f"missing required arguments: {', '.join(missing)}")
        self._validate_urls(payload)

        if tool_id in {"crawl", "map"}:
            payload.setdefault("allow_external", False)
            payload["limit"] = max(1, min(int(payload.get("limit", 50)), 100))
            payload["max_depth"] = max(1, min(int(payload.get("max_depth", 1)), 5))
            payload["max_breadth"] = max(1, min(int(payload.get("max_breadth", 20)), 100))
        if tool_id == "search":
            payload["max_results"] = max(1, min(int(payload.get("max_results", 5)), 20))
            payload.setdefault("search_depth", "basic")
            payload.setdefault("safe_search", True)
            payload.setdefault("include_usage", True)
        if tool_id == "extract":
            urls = payload.get("urls")
            if not isinstance(urls, list) or not 1 <= len(urls) <= 20:
                raise ValueError("Tavily extract requires 1 to 20 public URLs")
            payload.setdefault("extract_depth", "basic")
            payload.setdefault("include_usage", True)

        data = await self._request(
            str(descriptor.metadata["endpoint"]),
            payload,
            timeout_seconds=timeout_seconds,
        )
        usage = data.get("usage")
        if isinstance(usage, dict):
            credits = usage.get("credits")
            if isinstance(credits, (int, float)) and not isinstance(credits, bool):
                record_usage("tavily_credits", max(0, int(credits)))
        return {
            "status": "completed",
            "data": data,
            "metadata": {
                "provider": self.name,
                "endpoint": descriptor.metadata["endpoint"],
                "credits_used": usage.get("credits") if isinstance(usage, dict) else None,
            },
        }


class ExaToolProvider(_JsonPostProvider):
    name = "exa"
    base_url = "https://api.exa.ai"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            api_key if api_key is not None else os.getenv("EXA_API_KEY", "").strip(),
            client=client,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": str(self.api_key or ""),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _build_tools(self) -> dict[str, ToolDescriptor]:
        return {
            "search": ToolDescriptor(
                ref="exa:search",
                provider=self.name,
                tool_id="search",
                name="Exa semantic web search",
                description="Search the web semantically and optionally return extracted text/highlights.",
                input_schema=_schema(
                    {
                        "query": _str("Search query"),
                        "numResults": {"type": "integer", "minimum": 1, "maximum": 25},
                        "includeDomains": _string_array(max_items=50),
                        "excludeDomains": _string_array(max_items=50),
                        "startPublishedDate": {"type": "string"},
                        "endPublishedDate": {"type": "string"},
                        "category": {"type": "string"},
                        "text": {"type": "boolean"},
                        "highlights": {"type": "boolean"},
                        "summary": {"type": "boolean"},
                    },
                    ["query"],
                ),
                tags=["web", "search", "semantic", "research", "exa"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/search", "official": True},
            ),
            "contents": ToolDescriptor(
                ref="exa:contents",
                provider=self.name,
                tool_id="contents",
                name="Exa page contents",
                description="Retrieve text, highlights, summaries and metadata for public URLs.",
                input_schema=_schema(
                    {
                        "urls": {
                            "type": "array",
                            "items": {"type": "string", "format": "uri"},
                            "minItems": 1,
                            "maxItems": 20,
                        },
                        "text": {"type": "boolean"},
                        "highlights": {"type": "boolean"},
                        "summary": {"type": "boolean"},
                        "maxAgeHours": {"type": "integer", "minimum": -1, "maximum": 720},
                        "subpages": {"type": "integer", "minimum": 0, "maximum": 5},
                        "subpageTarget": {"type": "string", "minLength": 1, "maxLength": 100},
                    },
                    ["urls"],
                ),
                tags=["web", "contents", "extract", "highlights", "exa"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/contents", "official": True},
            ),
        }

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
        allowed = set((descriptor.input_schema.get("properties") or {}).keys())
        raw = {key: value for key, value in arguments.items() if key in allowed and value is not None}
        missing = [key for key in descriptor.input_schema.get("required") or [] if key not in raw]
        if missing:
            raise ValueError(f"missing required arguments: {', '.join(missing)}")

        payload: dict[str, Any]
        if tool_id == "search":
            payload = {
                key: value
                for key, value in raw.items()
                if key not in {"text", "highlights", "summary"}
            }
            payload["numResults"] = max(1, min(int(payload.get("numResults", 10)), 25))
            contents: dict[str, Any] = {}
            if raw.get("text"):
                contents["text"] = True
            if raw.get("highlights"):
                contents["highlights"] = True
            if raw.get("summary"):
                contents["summary"] = {}
            if contents:
                payload["contents"] = contents
        else:
            urls = raw.get("urls")
            if not isinstance(urls, list) or not 1 <= len(urls) <= 20:
                raise ValueError("Exa contents requires 1 to 20 public URLs")
            for url in urls:
                validate_public_http_url(str(url))
            payload = dict(raw)
            if payload.pop("summary", False):
                payload["summary"] = {}
            payload.setdefault("text", True)
            payload["subpages"] = max(0, min(int(payload.get("subpages", 0)), 5))

        data = await self._request(
            str(descriptor.metadata["endpoint"]),
            payload,
            timeout_seconds=timeout_seconds,
        )
        costs = data.get("costDollars")
        total = costs.get("total") if isinstance(costs, dict) else None
        if isinstance(total, (int, float)) and not isinstance(total, bool):
            record_usage("exa_cost_microusd", max(0, round(float(total) * 1_000_000)))
        return {
            "status": "completed",
            "data": data,
            "metadata": {
                "provider": self.name,
                "endpoint": descriptor.metadata["endpoint"],
                "cost_dollars": total,
            },
        }


def build_research_brand_providers() -> list[TavilyToolProvider | ExaToolProvider]:
    return [TavilyToolProvider(), ExaToolProvider()]
