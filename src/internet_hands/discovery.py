from __future__ import annotations

import asyncio
import json
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

from .fetcher import fetch_url

OPENAPI_HINTS = ("openapi", "swagger", "api-docs")
COMMON_OPENAPI_PATHS = (
    "/openapi.json",
    "/openapi.yaml",
    "/openapi.yml",
    "/swagger.json",
    "/swagger.yaml",
    "/v3/api-docs",
)
MACHINE_TYPES = {
    "application/rss+xml": "rss",
    "application/atom+xml": "atom",
    "application/feed+json": "json_feed",
    "application/json+oembed": "oembed",
    "text/xml": "xml_feed",
}


class _MachineLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self.anchors: list[str] = []
        self._json_ld = False
        self._json_ld_buffer: list[str] = []
        self.json_ld: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value for key, value in attrs if value is not None}
        lowered = tag.lower()
        if lowered == "link" and values.get("href"):
            self.links.append(values)
        elif lowered == "a" and values.get("href"):
            self.anchors.append(values["href"])
        elif lowered == "script" and values.get("type", "").lower() == "application/ld+json":
            self._json_ld = True
            self._json_ld_buffer = []

    def handle_data(self, data: str) -> None:
        if self._json_ld:
            self._json_ld_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or not self._json_ld:
            return
        raw = "".join(self._json_ld_buffer).strip()
        self._json_ld = False
        self._json_ld_buffer = []
        if not raw:
            return
        try:
            self.json_ld.append(json.loads(raw))
        except json.JSONDecodeError:
            return


def discover_from_html(html: str, base_url: str) -> dict[str, Any]:
    parser = _MachineLinkParser()
    parser.feed(html)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, href: str, source: str, confidence: str = "high") -> None:
        absolute = urljoin(base_url, href)
        parts = urlsplit(absolute)
        if parts.scheme not in {"http", "https"}:
            return
        clean = parts._replace(fragment="").geturl()
        key = (kind, clean)
        if key in seen:
            return
        seen.add(key)
        candidates.append(
            {
                "kind": kind,
                "url": clean,
                "source": source,
                "confidence": confidence,
            }
        )

    for link in parser.links:
        href = link.get("href")
        if not href:
            continue
        mime = link.get("type", "").lower()
        rel_tokens = {token.lower() for token in link.get("rel", "").split()}
        kind = MACHINE_TYPES.get(mime)
        if kind:
            add(kind, href, "html:link")
        if "manifest" in rel_tokens:
            add("web_manifest", href, "html:link")
        lowered_href = href.lower()
        if any(hint in lowered_href for hint in OPENAPI_HINTS):
            add("openapi_candidate", href, "html:link")

    for href in parser.anchors:
        lowered_href = href.lower()
        if any(hint in lowered_href for hint in OPENAPI_HINTS):
            add("openapi_candidate", href, "html:anchor", confidence="medium")

    return {
        "candidates": candidates,
        "json_ld": parser.json_ld,
    }


def _robots_sitemaps(text: str, base_url: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        key, separator, raw_value = line.partition(":")
        if not separator or key.strip().lower() != "sitemap":
            continue
        value = urljoin(base_url, raw_value.strip())
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return values


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


async def discover_public_interfaces(
    url: str,
    *,
    probe_openapi: bool = False,
) -> dict[str, Any]:
    page = await fetch_url(url, include_body=True, max_bytes=5_000_000)
    html_result = discover_from_html(page.body_text or "", page.final_url)
    origin = _origin(page.final_url)

    sitemaps: list[str] = []
    robots_error: str | None = None
    try:
        robots = await fetch_url(
            f"{origin}/robots.txt",
            include_body=True,
            max_bytes=2_000_000,
        )
        if robots.status_code < 400 and robots.body_text:
            sitemaps = _robots_sitemaps(robots.body_text, origin)
    except Exception as exc:  # noqa: BLE001 -- discovery returns partial results
        robots_error = f"{type(exc).__name__}: {exc}"

    probes: list[dict[str, Any]] = []
    if probe_openapi:
        probes = await _probe_common_openapi(origin)

    return {
        "url": page.final_url,
        "captured_at": page.captured_at.isoformat(),
        "sha256": page.sha256,
        "machine_interfaces": html_result["candidates"],
        "sitemaps": sitemaps,
        "json_ld": html_result["json_ld"],
        "openapi_probes": probes,
        "robots_error": robots_error,
        "policy": {
            "probe_openapi": probe_openapi,
            "probe_paths": list(COMMON_OPENAPI_PATHS) if probe_openapi else [],
            "note": "Discovery is bounded to published metadata and a small fixed OpenAPI path set.",
        },
    }


async def _probe_common_openapi(origin: str) -> list[dict[str, Any]]:
    async def probe(path: str) -> dict[str, Any] | None:
        target = urljoin(origin, path)
        try:
            result = await fetch_url(target, include_body=True, max_bytes=5_000_000)
        except Exception:
            return None
        body = (result.body_text or "").lstrip().lower()
        content_type = (result.content_type or "").lower()
        looks_like_spec = (
            result.status_code < 400
            and (
                "json" in content_type
                or "yaml" in content_type
                or body.startswith(("{", "openapi:", "swagger:"))
            )
            and ("openapi" in body[:4000] or "swagger" in body[:4000])
        )
        if not looks_like_spec:
            return None
        return {
            "url": result.final_url,
            "status_code": result.status_code,
            "content_type": result.content_type,
            "sha256": result.sha256,
        }

    results = await asyncio.gather(*(probe(path) for path in COMMON_OPENAPI_PATHS))
    return [item for item in results if item is not None]
