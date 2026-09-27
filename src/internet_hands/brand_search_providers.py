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


def _str(description: str = "", *, max_length: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "string"}
    if description:
        result["description"] = description
    if max_length is not None:
        result["maxLength"] = max_length
    return result


def _string_array(*, max_items: int = 50) -> dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "string"},
        "maxItems": max_items,
    }


def _clean_domains(value: Any, *, maximum: int = 50) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("domain filters must be arrays")
    result: list[str] = []
    for item in value[:maximum]:
        domain = str(item or "").strip().lower().rstrip(".")
        if not domain:
            continue
        if "://" in domain or "/" in domain or any(ch.isspace() for ch in domain):
            raise ValueError("domain filters must contain hostnames only")
        if not re.fullmatch(r"[a-z0-9.-]{1,253}", domain):
            raise ValueError("invalid domain filter")
        result.append(domain)
    return result


class YouSearchProvider:
    """Documented You.com Search/Contents/Research APIs with strict request normalization."""

    name = "you"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("YDC_API_KEY", "").strip()
        self.client = client
        self._tools = self._build_tools()

    @staticmethod
    def _build_tools() -> dict[str, ToolDescriptor]:
        return {
            "search": ToolDescriptor(
                ref="you:search",
                provider="you",
                tool_id="search",
                name="You.com web search",
                description=(
                    "Search web and news with LLM-ready snippets, highlights, or bounded "
                    "full-page extraction through You.com's documented Search API."
                ),
                input_schema=_schema(
                    {
                        "query": _str("Search query", max_length=4000),
                        "count": {"type": "integer", "minimum": 1, "maximum": 50},
                        "freshness": _str("day/week/month/year or documented date range", max_length=64),
                        "offset": {"type": "integer", "minimum": 0, "maximum": 9},
                        "country": _str("Country code", max_length=8),
                        "language": _str("BCP-47 language code", max_length=16),
                        "safesearch": {
                            "type": "string",
                            "enum": ["off", "moderate", "strict"],
                        },
                        "knowledge": {"type": "string", "enum": ["core"]},
                        "include_domains": _string_array(max_items=50),
                        "exclude_domains": _string_array(max_items=50),
                        "boost_domains": _string_array(max_items=50),
                        "extraction_mode": {
                            "type": "string",
                            "enum": ["snippets", "highlights", "full_page"],
                        },
                    },
                    ["query"],
                ),
                tags=["web", "search", "news", "rag", "you.com", "highlights"],
                requires_auth=True,
                side_effecting=False,
                metadata={
                    "endpoint": "https://ydc-index.io/v1/search",
                    "official": True,
                },
            ),
            "contents": ToolDescriptor(
                ref="you:contents",
                provider="you",
                tool_id="contents",
                name="You.com page contents",
                description=(
                    "Extract clean Markdown, HTML, and metadata from a bounded list of known "
                    "public URLs through You.com's documented Contents API."
                ),
                input_schema=_schema(
                    {
                        "urls": {
                            "type": "array",
                            "items": {"type": "string", "format": "uri"},
                            "minItems": 1,
                            "maxItems": 10,
                        },
                        "formats": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["html", "markdown", "metadata"],
                            },
                            "minItems": 1,
                            "maxItems": 3,
                        },
                        "crawl_timeout": {"type": "integer", "minimum": 1, "maximum": 60},
                        "max_age": {"type": "integer", "minimum": 0, "maximum": 604800},
                    },
                    ["urls"],
                ),
                tags=["web", "contents", "extract", "markdown", "you.com"],
                requires_auth=True,
                side_effecting=False,
                metadata={
                    "endpoint": "https://ydc-index.io/v1/contents",
                    "official": True,
                },
            ),
            "research": ToolDescriptor(
                ref="you:research",
                provider="you",
                tool_id="research",
                name="You.com cited research",
                description=(
                    "Run a bounded cited research request with documented source controls. "
                    "Background/frontier mode is intentionally excluded from this synchronous tool."
                ),
                input_schema=_schema(
                    {
                        "input": _str("Research question", max_length=40000),
                        "research_effort": {
                            "type": "string",
                            "enum": ["lite", "standard", "deep", "exhaustive"],
                        },
                        "include_domains": _string_array(max_items=50),
                        "exclude_domains": _string_array(max_items=50),
                        "boost_domains": _string_array(max_items=50),
                        "freshness": _str(max_length=64),
                        "country": _str(max_length=8),
                    },
                    ["input"],
                ),
                tags=["web", "research", "citations", "agent", "you.com"],
                requires_auth=True,
                side_effecting=False,
                metadata={
                    "endpoint": "https://api.you.com/v1/research",
                    "official": True,
                },
            ),
        }

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
        return [descriptor for _, descriptor in rows[: max(1, min(int(limit), 50))]]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise ValueError(f"unknown You.com tool: {tool_id}") from exc

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("YDC_API_KEY is not configured")
        return {
            "X-API-Key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _post(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: int,
    ) -> Any:
        validate_public_http_url(url)
        timeout = max(1.0, min(float(timeout_seconds), 300.0))
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
                response = await client.post(url, headers=self._headers(), json=payload)
                response.raise_for_status()
        return response.json()

    @staticmethod
    def _domain_controls(arguments: dict[str, Any]) -> dict[str, list[str]]:
        include = _clean_domains(arguments.get("include_domains"))
        exclude = _clean_domains(arguments.get("exclude_domains"))
        boost = _clean_domains(arguments.get("boost_domains"))
        if include and exclude:
            raise ValueError("include_domains and exclude_domains cannot be combined")
        if include and boost:
            raise ValueError("include_domains and boost_domains cannot be combined")
        controls: dict[str, list[str]] = {}
        if include:
            controls["include_domains"] = include
        if exclude:
            controls["exclude_domains"] = exclude
        if boost:
            controls["boost_domains"] = boost
        return controls

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
        endpoint = str(descriptor.metadata["endpoint"])

        if tool_id == "search":
            query = str(arguments.get("query") or "").strip()
            if not query:
                raise ValueError("query is required")
            payload: dict[str, Any] = {
                "query": query[:4000],
                "count": max(1, min(int(arguments.get("count", 10)), 50)),
                "offset": max(0, min(int(arguments.get("offset", 0)), 9)),
                **self._domain_controls(arguments),
            }
            for key in ("freshness", "country", "language", "knowledge"):
                value = arguments.get(key)
                if value is not None:
                    payload[key] = str(value)
            safesearch = str(arguments.get("safesearch") or "moderate").strip().lower()
            if safesearch not in {"off", "moderate", "strict"}:
                raise ValueError("invalid safesearch value")
            payload["safesearch"] = safesearch
            extraction_mode = str(arguments.get("extraction_mode") or "snippets")
            if extraction_mode not in {"snippets", "highlights", "full_page"}:
                raise ValueError("invalid extraction_mode")
            if extraction_mode != "snippets":
                payload["extraction"] = {"extraction_mode": extraction_mode}
            data = await self._post(endpoint, payload, timeout_seconds=timeout_seconds)
            record_usage("you_search_calls", 1)

        elif tool_id == "contents":
            urls = arguments.get("urls")
            if not isinstance(urls, list) or not 1 <= len(urls) <= 10:
                raise ValueError("You.com contents requires 1 to 10 public URLs")
            normalized_urls = [str(url) for url in urls]
            for url in normalized_urls:
                validate_public_http_url(url)
            formats = arguments.get("formats") or ["markdown", "metadata"]
            if not isinstance(formats, list):
                raise ValueError("formats must be an array")
            normalized_formats = [str(value) for value in formats]
            if not normalized_formats or any(
                value not in {"html", "markdown", "metadata"}
                for value in normalized_formats
            ):
                raise ValueError("formats contains an unsupported value")
            payload = {
                "urls": normalized_urls,
                "formats": normalized_formats[:3],
                "crawl_timeout": max(1, min(int(arguments.get("crawl_timeout", 10)), 60)),
            }
            if arguments.get("max_age") is not None:
                payload["max_age"] = max(0, min(int(arguments["max_age"]), 604800))
            data = await self._post(endpoint, payload, timeout_seconds=timeout_seconds)
            record_usage("you_content_pages", len(normalized_urls))

        elif tool_id == "research":
            prompt = str(arguments.get("input") or "").strip()
            if not prompt:
                raise ValueError("input is required")
            effort = str(arguments.get("research_effort") or "standard").strip().lower()
            if effort not in {"lite", "standard", "deep", "exhaustive"}:
                raise ValueError("unsupported research_effort")
            payload = {
                "input": prompt[:40000],
                "research_effort": effort,
                "background": False,
            }
            source_control = self._domain_controls(arguments)
            for key in ("freshness", "country"):
                value = arguments.get(key)
                if value is not None:
                    source_control[key] = str(value)
            if source_control:
                payload["source_control"] = source_control
            data = await self._post(endpoint, payload, timeout_seconds=max(timeout_seconds, 120))
            record_usage("you_research_calls", 1)

        else:
            raise ValueError(f"unknown You.com tool: {tool_id}")

        return {
            "status": "completed",
            "data": data,
            "metadata": {
                "provider": self.name,
                "endpoint": endpoint,
                "official": True,
            },
        }

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        del job_id, wait_seconds
        raise ValueError("You.com tools exposed by OpenCrawl complete inline")

    async def result_page(
        self,
        result_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        del result_id, offset, limit
        raise ValueError("You.com tools exposed by OpenCrawl return bounded inline results")


def build_brand_search_providers() -> list[YouSearchProvider]:
    return [YouSearchProvider()]
