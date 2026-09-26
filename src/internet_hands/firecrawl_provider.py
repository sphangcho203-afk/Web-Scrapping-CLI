from __future__ import annotations

import asyncio
import os
import time
from typing import Any
from urllib.parse import quote

import httpx

from .capability_economics import FIRECRAWL_WORK_BUDGETS
from .execution_meter import record_usage
from .policy import validate_public_http_url
from .tool_mesh import ToolDescriptor

_TERMINAL = {"completed", "failed", "cancelled"}
_RUNNING = {"pending", "processing", "scraping", "queued", "running"}
_SENSITIVE_HEADER_NAMES = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "x-api-key",
    "x-rapidapi-key",
}


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
    }
    if required:
        result["required"] = required
    return result


def _str_schema(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _normalize_status(value: Any) -> str:
    status = str(value or "").strip().casefold()
    if status in {"completed", "success", "succeeded"}:
        return "completed"
    if status in {"failed", "error", "cancelled", "canceled"}:
        return "failed"
    if status in _RUNNING or not status:
        return "running"
    return status


class FirecrawlToolProvider:
    """Firecrawl v2 provider for search, scrape, crawl, map, batch and agent jobs."""

    name = "firecrawl"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None else os.getenv("FIRECRAWL_API_KEY", "").strip()
        )
        configured_base = base_url or os.getenv("FIRECRAWL_API_URL", "").strip()
        self.base_url = (configured_base or "https://api.firecrawl.dev").rstrip("/")
        self.client = client
        self._tools = self._build_tools()

    @staticmethod
    def _build_tools() -> dict[str, ToolDescriptor]:
        return {
            "search": ToolDescriptor(
                ref="firecrawl:search",
                provider="firecrawl",
                tool_id="search",
                name="Firecrawl web search",
                description=(
                    "Search the live web and optionally scrape result pages into clean, "
                    "LLM-ready content."
                ),
                input_schema=_schema(
                    {
                        "query": _str_schema("Natural-language web search query"),
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                        "scrapeOptions": {"type": "object"},
                        "includeDomains": {"type": "array", "items": {"type": "string"}},
                        "excludeDomains": {"type": "array", "items": {"type": "string"}},
                        "country": {"type": "string"},
                        "tbs": {"type": "string"},
                        "location": {"type": "string"},
                    },
                    ["query"],
                ),
                tags=["web", "search", "research", "firecrawl"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/v2/search", "mode": "sync", "api": "v2"},
            ),
            "scrape": ToolDescriptor(
                ref="firecrawl:scrape",
                provider="firecrawl",
                tool_id="scrape",
                name="Firecrawl scrape",
                description=(
                    "Render and extract one public URL as Markdown, HTML, structured JSON, "
                    "screenshots, links, highlights, questions, or other supported formats."
                ),
                input_schema=_schema(
                    {
                        "url": _str_schema("Public HTTP(S) URL to scrape"),
                        "formats": {"type": "array"},
                        "onlyMainContent": {"type": "boolean"},
                        "onlyCleanContent": {"type": "boolean"},
                        "waitFor": {"type": "integer", "minimum": 0},
                        "timeout": {"type": "integer", "minimum": 1},
                        "mobile": {"type": "boolean"},
                        "proxy": {"type": "string"},
                        "location": {"type": "object"},
                        "parsers": {"type": "array"},
                        "headers": {"type": "object"},
                        "maxAge": {"type": "integer", "minimum": 0},
                        "zeroDataRetention": {"type": "boolean"},
                    },
                    ["url"],
                ),
                tags=["web", "scrape", "markdown", "extract", "firecrawl"],
                requires_auth=True,
                side_effecting=False,
                metadata={
                    "endpoint": "/v2/scrape",
                    "mode": "sync",
                    "api": "v2",
                    "note": "interactive actions are intentionally separated from read-only scrape",
                },
            ),
            "map": ToolDescriptor(
                ref="firecrawl:map",
                provider="firecrawl",
                tool_id="map",
                name="Firecrawl site map",
                description="Discover and rank public URLs across a site without fully crawling every page.",
                input_schema=_schema(
                    {
                        "url": _str_schema("Public site root URL"),
                        "search": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1},
                        "includeSubdomains": {"type": "boolean"},
                        "ignoreSitemap": {"type": "boolean"},
                        "sitemapOnly": {"type": "boolean"},
                        "ignoreCache": {"type": "boolean"},
                    },
                    ["url"],
                ),
                tags=["web", "map", "links", "discovery", "firecrawl"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/v2/map", "mode": "sync", "api": "v2"},
            ),
            "crawl": ToolDescriptor(
                ref="firecrawl:crawl",
                provider="firecrawl",
                tool_id="crawl",
                name="Firecrawl site crawl",
                description=(
                    "Start an asynchronous public-site crawl and collect LLM-ready documents."
                ),
                input_schema=_schema(
                    {
                        "url": _str_schema("Public site root URL"),
                        "limit": {"type": "integer", "minimum": 1},
                        "maxDiscoveryDepth": {"type": "integer", "minimum": 0},
                        "includePaths": {"type": "array", "items": {"type": "string"}},
                        "excludePaths": {"type": "array", "items": {"type": "string"}},
                        "allowExternalLinks": {"type": "boolean"},
                        "allowSubdomains": {"type": "boolean"},
                        "crawlEntireDomain": {"type": "boolean"},
                        "ignoreSitemap": {"type": "boolean"},
                        "scrapeOptions": {"type": "object"},
                        "zeroDataRetention": {"type": "boolean"},
                    },
                    ["url"],
                ),
                tags=["web", "crawl", "corpus", "async", "firecrawl"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/v2/crawl", "mode": "async", "api": "v2"},
            ),
            "batch-scrape": ToolDescriptor(
                ref="firecrawl:batch-scrape",
                provider="firecrawl",
                tool_id="batch-scrape",
                name="Firecrawl batch scrape",
                description="Start an asynchronous scrape for multiple public URLs.",
                input_schema=_schema(
                    {
                        "urls": {
                            "type": "array",
                            "items": {"type": "string", "format": "uri"},
                            "minItems": 1,
                        },
                        "formats": {"type": "array"},
                        "onlyMainContent": {"type": "boolean"},
                        "onlyCleanContent": {"type": "boolean"},
                        "proxy": {"type": "string"},
                        "zeroDataRetention": {"type": "boolean"},
                    },
                    ["urls"],
                ),
                tags=["web", "scrape", "batch", "async", "firecrawl"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/v2/batch/scrape", "mode": "async", "api": "v2"},
            ),
            "agent": ToolDescriptor(
                ref="firecrawl:agent",
                provider="firecrawl",
                tool_id="agent",
                name="Firecrawl research agent",
                description=(
                    "Run Firecrawl's web research agent from a prompt, optionally constrained by "
                    "public URLs and a structured output schema."
                ),
                input_schema=_schema(
                    {
                        "prompt": _str_schema("Research/extraction goal"),
                        "urls": {"type": "array", "items": {"type": "string"}},
                        "schema": {"type": "object"},
                        "maxCredits": {"type": "number", "exclusiveMinimum": 0},
                        "effort": {"type": "string", "enum": ["low", "medium", "high"]},
                        "model": {"type": "string"},
                        "zeroDataRetention": {"type": "boolean"},
                    },
                    ["prompt"],
                ),
                tags=["web", "research", "agent", "async", "firecrawl"],
                requires_auth=True,
                side_effecting=False,
                metadata={"endpoint": "/v2/agent", "mode": "async", "api": "v2"},
            ),
            "extract": ToolDescriptor(
                ref="firecrawl:extract",
                provider="firecrawl",
                tool_id="extract",
                name="Firecrawl structured extract",
                description=(
                    "Legacy-compatible structured extraction job across one or more public URLs. "
                    "Prefer firecrawl:agent for new autonomous research flows."
                ),
                input_schema=_schema(
                    {
                        "urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                        },
                        "prompt": {"type": "string"},
                        "schema": {"type": "object"},
                        "enableWebSearch": {"type": "boolean"},
                        "zeroDataRetention": {"type": "boolean"},
                    },
                    ["urls"],
                ),
                tags=["web", "extract", "structured-data", "async", "firecrawl"],
                requires_auth=True,
                side_effecting=False,
                metadata={
                    "endpoint": "/v2/extract",
                    "mode": "async",
                    "api": "v2",
                    "superseded_by": "firecrawl:agent",
                },
            ),
            "interact": ToolDescriptor(
                ref="firecrawl:interact",
                provider="firecrawl",
                tool_id="interact",
                name="Firecrawl interact",
                description=(
                    "Interact with a prior Firecrawl scrape browser session using a natural-language "
                    "prompt. This can click or submit page controls and is therefore side-effecting."
                ),
                input_schema=_schema(
                    {
                        "scrape_id": _str_schema("Firecrawl scrape job/session identifier"),
                        "prompt": _str_schema("Browser interaction instruction"),
                        "timeout": {"type": "number", "minimum": 1, "maximum": 300},
                        "ttl": {"type": "number", "minimum": 30, "maximum": 3600},
                        "activityTtl": {"type": "number", "minimum": 10, "maximum": 3600},
                    },
                    ["scrape_id", "prompt"],
                ),
                tags=["web", "browser", "interact", "firecrawl"],
                requires_auth=True,
                side_effecting=True,
                metadata={
                    "endpoint": "/v2/scrape/{scrape_id}/interact",
                    "mode": "sync",
                    "api": "v2",
                    "prompt_only": True,
                },
            ),
        }

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("FIRECRAWL_API_KEY is not configured")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def status(self) -> dict[str, Any]:
        return {
            "configured": bool(self.api_key),
            "searchable": True,
            "executable": bool(self.api_key),
            "kind": "web-context-api",
            "api": "v2",
            "base_url": self.base_url,
            "tool_count": len(self._tools),
            "capabilities": [
                "search",
                "scrape",
                "map",
                "crawl",
                "batch-scrape",
                "agent",
                "extract",
                "interact",
            ],
        }

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        words = [word for word in query.casefold().split() if word]
        ranked: list[tuple[int, ToolDescriptor]] = []
        for descriptor in self._tools.values():
            haystack = " ".join(
                [descriptor.tool_id, descriptor.name, descriptor.description, *descriptor.tags]
            ).casefold()
            score = sum(4 if word in descriptor.name.casefold() else 1 for word in words if word in haystack)
            if score or not words:
                ranked.append((score, descriptor))
        ranked.sort(key=lambda row: (-row[0], row[1].tool_id))
        return [self._copy(item) for _, item in ranked[: max(1, min(limit, 50))]]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        try:
            return self._copy(self._tools[tool_id])
        except KeyError as exc:
            raise ValueError(f"unknown Firecrawl tool: {tool_id}") from exc

    @staticmethod
    def _copy(item: ToolDescriptor) -> ToolDescriptor:
        return ToolDescriptor(
            ref=item.ref,
            provider=item.provider,
            tool_id=item.tool_id,
            name=item.name,
            description=item.description,
            input_schema=dict(item.input_schema),
            output_schema=dict(item.output_schema),
            tags=list(item.tags),
            requires_auth=item.requires_auth,
            side_effecting=item.side_effecting,
            metadata=dict(item.metadata),
        )

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
        del account, options
        descriptor = await self.describe(tool_id)
        payload = dict(arguments)
        self._validate_arguments(tool_id, payload)
        if tool_id in FIRECRAWL_WORK_BUDGETS:
            field, default, maximum = FIRECRAWL_WORK_BUDGETS[tool_id]
            try:
                units = int(payload.get(field, default))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{field} must be an integer") from exc
            if not 1 <= units <= maximum:
                raise ValueError(f"{field} must be between 1 and {maximum}")
            payload[field] = units
        if tool_id == "batch-scrape" and not 1 <= len(payload.get("urls") or []) <= 20:
            raise ValueError("batch scrape requires 1 to 20 URLs")
        if tool_id == "extract":
            raise ValueError("unbounded extraction is unavailable; use a bounded agent job")

        if tool_id == "interact":
            scrape_id = str(payload.pop("scrape_id"))
            path = f"/v2/scrape/{quote(scrape_id, safe='')}/interact"
        else:
            path = str(descriptor.metadata["endpoint"])

        response = await self._request(
            "POST",
            path,
            json=payload,
            timeout=max(1.0, min(float(timeout_seconds), 600.0)),
        )
        body = response.json()
        if not isinstance(body, dict):
            raise TypeError("Firecrawl returned a non-object response")
        if body.get("success") is False:
            raise RuntimeError(str(body.get("error") or "web operation failed"))
        record_usage("firecrawl_work_units", (
            len(payload["urls"]) if tool_id == "batch-scrape" else
            payload.get("limit", 1) if tool_id in {"crawl", "map", "search"} else
            payload.get("maxCredits", 1) if tool_id == "agent" else 1
        ))

        if descriptor.metadata.get("mode") != "async":
            return {
                "status": "completed",
                "job_id": None,
                "result_id": None,
                "data": body.get("data", body),
                "error": None,
                "metadata": {
                    "tool": tool_id,
                    "api": "v2",
                    "credits_used": body.get("creditsUsed"),
                    "scrape_id": body.get("id") if tool_id == "scrape" else None,
                },
            }

        raw_id = body.get("id") or body.get("jobId")
        if not raw_id:
            raise RuntimeError("Firecrawl async job did not return an id")
        job_id = f"{tool_id}:{raw_id}"
        if wait_seconds > 0:
            status_payload = await self.job_status(job_id, wait_seconds=wait_seconds)
            normalized = _normalize_status(status_payload.get("status"))
            result_id = job_id if tool_id in {"crawl", "batch-scrape"} else None
            return {
                "status": normalized,
                "job_id": job_id,
                "result_id": result_id,
                "data": status_payload,
                "error": status_payload.get("error") if normalized == "failed" else None,
                "metadata": {"tool": tool_id, "api": "v2"},
            }

        return {
            "status": "running",
            "job_id": job_id,
            "result_id": job_id if tool_id in {"crawl", "batch-scrape"} else None,
            "data": body,
            "error": None,
            "metadata": {"tool": tool_id, "api": "v2"},
        }

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        kind, raw_id = self._split_job_id(job_id)
        endpoint = self._status_endpoint(kind, raw_id)
        deadline = time.monotonic() + max(0, wait_seconds)
        while True:
            response = await self._request("GET", endpoint, timeout=60.0)
            body = response.json()
            if not isinstance(body, dict):
                raise TypeError("Firecrawl returned an invalid job status")
            normalized = _normalize_status(body.get("status"))
            body["meshStatus"] = normalized
            body["meshJobId"] = job_id
            if normalized in {"completed", "failed"} or wait_seconds <= 0:
                return body
            if time.monotonic() >= deadline:
                return body
            await asyncio.sleep(min(1.0, max(0.05, deadline - time.monotonic())))

    async def result_page(
        self, result_id: str, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        kind, raw_id = self._split_job_id(result_id)
        if kind not in {"crawl", "batch-scrape"}:
            raise NotImplementedError("Firecrawl paged results are supported for crawl/batch jobs")
        endpoint = self._status_endpoint(kind, raw_id)
        page_limit = max(1, min(limit, 1000))
        response = await self._request(
            "GET",
            endpoint,
            params={"skip": max(0, offset), "limit": page_limit},
            timeout=60.0,
        )
        body = response.json()
        if not isinstance(body, dict):
            raise TypeError("Firecrawl returned invalid paged results")
        return {
            "result_id": result_id,
            "offset": max(0, offset),
            "limit": page_limit,
            "status": body.get("status"),
            "total": body.get("total"),
            "completed": body.get("completed"),
            "credits_used": body.get("creditsUsed"),
            "items": body.get("data") or [],
            "next": body.get("next"),
        }

    def _validate_arguments(self, tool_id: str, payload: dict[str, Any]) -> None:
        urls: list[str] = []
        if isinstance(payload.get("url"), str):
            urls.append(payload["url"])
        if isinstance(payload.get("urls"), list):
            urls.extend(str(value) for value in payload["urls"] if isinstance(value, str))
        for url in urls:
            validate_public_http_url(url)

        headers = payload.get("headers")
        if isinstance(headers, dict):
            blocked = [name for name in headers if str(name).casefold() in _SENSITIVE_HEADER_NAMES]
            if blocked:
                raise PermissionError(
                    "Firecrawl target Authorization/Cookie/API-key headers are not accepted through the mesh"
                )

        if tool_id == "scrape" and payload.get("actions"):
            raise PermissionError(
                "Firecrawl read-only scrape does not accept actions; use firecrawl:interact explicitly"
            )
        if tool_id == "interact" and "code" in payload:
            raise PermissionError("Firecrawl interact is prompt-only through Internet Hands")

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.update(self._headers())
        url = f"{self.base_url}{path}"
        if self.client is not None:
            response = await self.client.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response
        timeout = kwargs.pop("timeout", 60.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response

    @staticmethod
    def _split_job_id(job_id: str) -> tuple[str, str]:
        kind, separator, raw_id = job_id.partition(":")
        if not separator or kind not in {"crawl", "batch-scrape", "agent", "extract"} or not raw_id:
            raise ValueError("invalid Firecrawl job id")
        return kind, raw_id

    @staticmethod
    def _status_endpoint(kind: str, raw_id: str) -> str:
        encoded = quote(raw_id, safe="")
        if kind == "crawl":
            return f"/v2/crawl/{encoded}"
        if kind == "batch-scrape":
            return f"/v2/batch/scrape/{encoded}"
        if kind == "agent":
            return f"/v2/agent/{encoded}"
        if kind == "extract":
            return f"/v2/extract/{encoded}"
        raise ValueError(f"unsupported Firecrawl job kind: {kind}")
