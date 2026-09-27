from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from .adapters import AdapterError, capture_with_backend
from .backends import module_available
from .browser import render_page
from .discovery import discover_from_html, discover_frontier_urls, discover_public_interfaces
from .execution_meter import record_usage
from .extractor import extract_document
from .fetcher import fetch_url
from .models import BrowserResult, FetchResult
from .policy import validate_public_http_url
from .tool_mesh import ToolDescriptor
from .web_search import SearchKind, brave_search

_CHALLENGE_MARKERS = (
    "captcha",
    "verify you are human",
    "checking your browser",
    "challenge-platform",
    "cf-chl-",
    "access denied",
    "unusual traffic",
)
_DYNAMIC_MARKERS = (
    'id="root"',
    "id='root'",
    'id="app"',
    "id='app'",
    "__next_data__",
    "__nuxt__",
    "webpack",
)


def _browser_fetch(result: BrowserResult) -> FetchResult:
    payload = result.html.encode("utf-8")
    return FetchResult(
        request_url=result.request_url,
        final_url=result.final_url,
        status_code=int(result.status_code or 200),
        headers={"x-opencrawl-backend": "native-playwright"},
        content_type="text/html; charset=utf-8",
        content_length=len(payload),
        sha256=result.sha256,
        elapsed_ms=0.0,
        captured_at=result.captured_at,
        body_text=result.html,
        body_base64=None,
    )


def _block_reason(result: FetchResult) -> str | None:
    body = (result.body_text or "")[:250_000].casefold()
    if result.status_code in {401, 403, 429}:
        return f"http_{result.status_code}"
    return next((marker for marker in _CHALLENGE_MARKERS if marker in body), None)


def _should_render(result: FetchResult, text_length: int, minimum_text: int) -> bool:
    if result.status_code >= 400:
        return False
    body = (result.body_text or "")[:250_000].casefold()
    if text_length < minimum_text:
        return True
    scripts = body.count("<script")
    if scripts >= 6 and any(marker in body for marker in _DYNAMIC_MARKERS):
        return True
    return False


def _backend_ready(name: str) -> bool:
    if name == "crawlee-http":
        return module_available("crawlee")
    return module_available(name)


async def resilient_public_fetch(
    url: str,
    *,
    render: str = "auto",
    backend: str = "auto",
    timeout_seconds: float = 30.0,
    max_bytes: int = 4_000_000,
    minimum_text: int = 240,
    discover_interfaces: bool = True,
    max_frontier_urls: int = 250,
) -> dict[str, Any]:
    """Collect a public page with bounded fallbacks and explicit anti-challenge behavior."""
    validate_public_http_url(url)
    render = str(render or "auto").strip().lower()
    backend = str(backend or "auto").strip().lower()
    if render not in {"auto", "never", "always"}:
        raise ValueError("render must be auto, never, or always")
    if backend not in {"auto", "native-http", "native-playwright", "crawlee-http", "crawl4ai", "scrapy"}:
        raise ValueError("unsupported intelligence backend")

    max_bytes = max(32_000, min(int(max_bytes), 8_000_000))
    minimum_text = max(1, min(int(minimum_text), 20_000))
    max_frontier_urls = max(0, min(int(max_frontier_urls), 5_000))
    timeout_seconds = max(1.0, min(float(timeout_seconds), 60.0))
    attempts: list[dict[str, Any]] = []

    async def capture_native() -> FetchResult:
        record_usage("intelligence_http_requests")
        return await fetch_url(
            url,
            timeout=timeout_seconds,
            max_bytes=max_bytes,
            include_body=True,
        )

    async def capture_playwright() -> FetchResult:
        record_usage("intelligence_browser_renders")
        rendered = await render_page(url, timeout_ms=int(timeout_seconds * 1000))
        return _browser_fetch(rendered)

    async def capture_external(name: str) -> FetchResult:
        if os.getenv("OPENCRAWL_EXTERNAL_BACKENDS_ENABLED", "").strip().lower() not in {
            "1", "true", "yes", "on"
        }:
            raise AdapterError("optional external crawler backends are disabled")
        if not _backend_ready(name):
            raise AdapterError(f"{name} is not installed")
        record_usage("intelligence_external_backend_requests")
        return await capture_with_backend(
            name,
            url,
            allow_external_network=True,
            max_bytes=max_bytes,
        )

    if backend == "native-playwright":
        chain = [("native-playwright", capture_playwright)]
    elif backend in {"crawlee-http", "crawl4ai", "scrapy"}:
        chain = [(backend, lambda: capture_external(backend))]
    elif backend == "native-http":
        chain = [("native-http", capture_native)]
    else:
        chain = [("native-http", capture_native)]

    selected: FetchResult | None = None
    selected_backend: str | None = None
    blocked: str | None = None

    for name, collector in chain:
        try:
            result = await collector()
            document = extract_document(result)
            blocked = _block_reason(result)
            attempts.append(
                {
                    "backend": name,
                    "status": "blocked" if blocked else "completed",
                    "http_status": result.status_code,
                    "text_length": len(document.text),
                    "sha256": result.sha256,
                    "reason": blocked,
                }
            )
            selected, selected_backend = result, name
        except Exception as exc:  # noqa: BLE001 - provider fallback boundary
            attempts.append(
                {
                    "backend": name,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                }
            )
            continue
        break

    if selected is None:
        raise RuntimeError("all configured collection backends failed")

    initial_document = extract_document(selected)

    # A challenge is an explicit stop condition. Do not turn browser rendering into
    # an anti-bot bypass mechanism.
    if blocked is None and backend == "auto" and render != "never":
        needs_render = render == "always" or _should_render(
            selected, len(initial_document.text), minimum_text
        )
        if needs_render and selected_backend != "native-playwright":
            try:
                rendered = await capture_playwright()
                rendered_document = extract_document(rendered)
                rendered_block = _block_reason(rendered)
                attempts.append(
                    {
                        "backend": "native-playwright",
                        "status": "blocked" if rendered_block else "completed",
                        "http_status": rendered.status_code,
                        "text_length": len(rendered_document.text),
                        "sha256": rendered.sha256,
                        "reason": rendered_block,
                    }
                )
                if rendered_block is None and len(rendered_document.text) >= len(initial_document.text):
                    selected = rendered
                    selected_backend = "native-playwright"
                    initial_document = rendered_document
                elif rendered_block:
                    blocked = rendered_block
            except Exception as exc:  # noqa: BLE001 - rendering fallback is best effort
                attempts.append(
                    {
                        "backend": "native-playwright",
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}"[:500],
                    }
                )

    # Optional OSS fallback engines are for reliability, not protection evasion.
    if (
        blocked is None
        and backend == "auto"
        and render != "never"
        and len(initial_document.text) < minimum_text
        and os.getenv("OPENCRAWL_EXTERNAL_BACKENDS_ENABLED", "").strip().lower()
        in {"1", "true", "yes", "on"}
    ):
        for name in ("crawl4ai", "crawlee-http", "scrapy"):
            if not _backend_ready(name):
                continue
            try:
                candidate = await capture_external(name)
                candidate_doc = extract_document(candidate)
                candidate_block = _block_reason(candidate)
                attempts.append(
                    {
                        "backend": name,
                        "status": "blocked" if candidate_block else "completed",
                        "http_status": candidate.status_code,
                        "text_length": len(candidate_doc.text),
                        "sha256": candidate.sha256,
                        "reason": candidate_block,
                    }
                )
                if candidate_block is None and len(candidate_doc.text) > len(initial_document.text):
                    selected, selected_backend, initial_document = candidate, name, candidate_doc
                    if len(initial_document.text) >= minimum_text:
                        break
            except Exception as exc:  # noqa: BLE001 - optional backend isolation
                attempts.append(
                    {
                        "backend": name,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}"[:500],
                    }
                )

    body = selected.body_text or ""
    published = (
        discover_from_html(body, selected.final_url)
        if discover_interfaces and body
        else {"candidates": [], "json_ld": []}
    )
    frontier = (
        discover_frontier_urls(
            body,
            selected.final_url,
            content_type=selected.content_type,
            limit=max_frontier_urls,
        )
        if max_frontier_urls and body
        else []
    )

    return {
        "status": "blocked" if blocked else "completed",
        "blocked": bool(blocked),
        "block_reason": blocked,
        "selected_backend": selected_backend,
        "attempts": attempts,
        "document": initial_document.model_dump(mode="json"),
        "published_interfaces": published["candidates"],
        "json_ld": published["json_ld"][:50],
        "frontier_urls": frontier,
        "provenance": {
            "request_url": selected.request_url,
            "final_url": selected.final_url,
            "http_status": selected.status_code,
            "content_type": selected.content_type,
            "content_length": selected.content_length,
            "sha256": selected.sha256,
            "captured_at": selected.captured_at.isoformat(),
        },
        "policy": {
            "public_http_only": True,
            "challenge_bypass": False,
            "robots_for_recursive_crawls": True,
        },
    }


class IntelligenceFabricProvider:
    name = "intelligence"

    def _descriptors(self) -> dict[str, ToolDescriptor]:
        return {
            "smart-fetch": ToolDescriptor(
                ref="intelligence:smart-fetch",
                provider=self.name,
                tool_id="smart-fetch",
                name="Resilient public web extraction",
                description=(
                    "Fetch and extract one public page, using guarded Playwright or installed "
                    "open-source crawler backends only when ordinary HTTP is insufficient."
                ),
                input_schema={
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {"type": "string"},
                        "render": {"enum": ["auto", "never", "always"]},
                        "backend": {
                            "enum": [
                                "auto",
                                "native-http",
                                "native-playwright",
                                "crawlee-http",
                                "crawl4ai",
                                "scrapy",
                            ]
                        },
                        "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 60},
                        "max_bytes": {"type": "integer", "minimum": 32000, "maximum": 8000000},
                        "minimum_text": {"type": "integer", "minimum": 1, "maximum": 20000},
                        "discover_interfaces": {"type": "boolean"},
                        "max_frontier_urls": {"type": "integer", "minimum": 0, "maximum": 5000},
                    },
                },
                tags=["web", "scrape", "extract", "playwright", "fallback", "provenance"],
                side_effecting=False,
                metadata={
                    "first_party": True,
                    "challenge_bypass": False,
                    "backends": [
                        "native-http",
                        "native-playwright",
                        "crawlee-http",
                        "crawl4ai",
                        "scrapy",
                    ],
                },
            ),
            "discover-interfaces": ToolDescriptor(
                ref="intelligence:discover-interfaces",
                provider=self.name,
                tool_id="discover-interfaces",
                name="Published interface discovery",
                description=(
                    "Discover sitemaps, feeds, JSON-LD and bounded published OpenAPI candidates "
                    "from a public website."
                ),
                input_schema={
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {"type": "string"},
                        "probe_openapi": {"type": "boolean"},
                    },
                },
                tags=["web", "api", "openapi", "sitemap", "feed", "discovery"],
                side_effecting=False,
                metadata={"first_party": True, "bounded_probes": True},
            ),
            "search-extract": ToolDescriptor(
                ref="intelligence:search-extract",
                provider=self.name,
                tool_id="search-extract",
                name="Search then extract evidence",
                description=(
                    "Search the public web through the configured search provider, then collect "
                    "and extract a bounded number of result pages with provenance."
                ),
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string"},
                        "count": {"type": "integer", "minimum": 1, "maximum": 5},
                        "render": {"enum": ["auto", "never", "always"]},
                    },
                },
                tags=["web", "search", "extract", "research", "evidence"],
                requires_auth=True,
                side_effecting=False,
                metadata={"first_party": True, "search_provider": "brave"},
            ),
        }

    async def status(self) -> dict[str, Any]:
        return {
            "configured": True,
            "searchable": True,
            "executable": True,
            "kind": "first-party-intelligence-fabric",
            "tool_count": len(self._descriptors()),
            "search_configured": bool(os.getenv("BRAVE_SEARCH_API_KEY")),
            "playwright": module_available("playwright"),
            "optional_backends_enabled": os.getenv(
                "OPENCRAWL_EXTERNAL_BACKENDS_ENABLED", ""
            ).strip().lower() in {"1", "true", "yes", "on"},
            "challenge_bypass": False,
        }

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        words = [word for word in re.split(r"\W+", query.casefold()) if word]
        rows: list[tuple[int, ToolDescriptor]] = []
        for descriptor in self._descriptors().values():
            haystack = " ".join(
                [descriptor.tool_id, descriptor.name, descriptor.description, *descriptor.tags]
            ).casefold()
            score = sum(4 if word in descriptor.name.casefold() else 1 for word in words if word in haystack)
            if score or not words:
                rows.append((score, descriptor))
        rows.sort(key=lambda row: (-row[0], row[1].tool_id))
        return [item for _, item in rows[: max(1, min(int(limit), 20))]]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        try:
            return self._descriptors()[tool_id]
        except KeyError as exc:
            raise ValueError(f"unknown intelligence tool: {tool_id}") from exc

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

        if tool_id == "smart-fetch":
            data = await resilient_public_fetch(
                str(arguments.get("url") or ""),
                render=str(arguments.get("render") or "auto"),
                backend=str(arguments.get("backend") or "auto"),
                timeout_seconds=float(arguments.get("timeout_seconds", timeout_seconds)),
                max_bytes=int(arguments.get("max_bytes", 4_000_000)),
                minimum_text=int(arguments.get("minimum_text", 240)),
                discover_interfaces=bool(arguments.get("discover_interfaces", True)),
                max_frontier_urls=int(arguments.get("max_frontier_urls", 250)),
            )
            return {"status": "completed", "data": data}

        if tool_id == "discover-interfaces":
            probe_openapi = bool(arguments.get("probe_openapi", False))
            record_usage("intelligence_http_requests", 2 + (6 if probe_openapi else 0))
            data = await discover_public_interfaces(
                str(arguments.get("url") or ""),
                probe_openapi=probe_openapi,
            )
            return {"status": "completed", "data": data}

        if tool_id == "search-extract":
            query = str(arguments.get("query") or "").strip()
            count = max(1, min(int(arguments.get("count", 3)), 5))
            record_usage("intelligence_search_requests")
            search = await brave_search(query, kind=SearchKind.WEB, count=count)
            rows = (((search.get("data") or {}).get("response") or {}).get("web") or {}).get("results") or []
            urls = [
                str(item.get("url"))
                for item in rows
                if isinstance(item, dict) and str(item.get("url") or "").startswith(("http://", "https://"))
            ][:count]
            semaphore = asyncio.Semaphore(3)

            async def collect(target: str) -> dict[str, Any]:
                async with semaphore:
                    try:
                        return await resilient_public_fetch(
                            target,
                            render=str(arguments.get("render") or "auto"),
                            timeout_seconds=min(float(timeout_seconds), 45.0),
                            max_frontier_urls=50,
                        )
                    except Exception as exc:  # noqa: BLE001 - result isolation boundary
                        return {"status": "failed", "url": target, "error": f"{type(exc).__name__}: {exc}"[:500]}

            pages = await asyncio.gather(*(collect(target) for target in urls))
            return {
                "status": "completed",
                "data": {
                    "query": query,
                    "search": search,
                    "pages": pages,
                    "result_count": len(pages),
                },
            }

        raise ValueError(f"unsupported intelligence tool: {tool_id}")

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        del job_id, wait_seconds
        raise ValueError("intelligence tools complete inline")

    async def result_page(
        self,
        result_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        del result_id, offset, limit
        raise ValueError("intelligence tools return bounded inline results")
