from __future__ import annotations

import asyncio
import fnmatch
import time
from collections import deque
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .execution_meter import record_usage
from .fetcher import DEFAULT_UA, extract_links, fetch_url
from .models import CrawlPage, CrawlResult
from .policy import validate_public_http_url

_SKIP_SUFFIXES = (
    ".7z", ".avi", ".bmp", ".css", ".eot", ".gif", ".ico", ".jpeg", ".jpg",
    ".js", ".m4a", ".m4v", ".mov", ".mp3", ".mp4", ".ogg", ".otf", ".png",
    ".rar", ".tar", ".tgz", ".ttf", ".wav", ".webm", ".webp", ".woff", ".woff2", ".zip",
)


def _normalize_url(url: str, *, preserve_query: bool) -> str:
    parts = urlsplit(url)
    query = parts.query if preserve_query else ""
    return parts._replace(fragment="", query=query).geturl()


def _same_scope(seed_host: str, candidate_host: str | None, include_subdomains: bool) -> bool:
    if not candidate_host:
        return False
    host = candidate_host.rstrip(".").casefold()
    root = seed_host.rstrip(".").casefold()
    return host == root or (include_subdomains and host.endswith("." + root))


def _path_allowed(url: str, include_paths: tuple[str, ...], exclude_paths: tuple[str, ...]) -> bool:
    path = urlsplit(url).path or "/"
    if include_paths and not any(fnmatch.fnmatch(path, pattern) for pattern in include_paths):
        return False
    if exclude_paths and any(fnmatch.fnmatch(path, pattern) for pattern in exclude_paths):
        return False
    return not path.casefold().endswith(_SKIP_SUFFIXES)


async def crawl(
    seed_url: str,
    *,
    max_pages: int = 25,
    delay_seconds: float = 0.35,
    respect_robots: bool = True,
    max_depth: int = 20,
    concurrency: int = 1,
    max_seconds: float = 120.0,
    include_paths: list[str] | tuple[str, ...] | None = None,
    exclude_paths: list[str] | tuple[str, ...] | None = None,
    include_subdomains: bool = False,
    preserve_query: bool = True,
    max_bytes_per_page: int = 2_000_000,
) -> CrawlResult:
    """Crawl a bounded public site with SSRF, robots, depth, time and fan-out controls."""
    validate_public_http_url(seed_url)
    if max_pages < 1 or max_pages > 500:
        raise ValueError("max_pages must be between 1 and 500")
    if max_depth < 0 or max_depth > 50:
        raise ValueError("max_depth must be between 0 and 50")
    if concurrency < 1 or concurrency > 12:
        raise ValueError("concurrency must be between 1 and 12")
    if max_seconds < 1 or max_seconds > 600:
        raise ValueError("max_seconds must be between 1 and 600")
    if max_bytes_per_page < 32_000 or max_bytes_per_page > 8_000_000:
        raise ValueError("max_bytes_per_page must be between 32000 and 8000000")

    include = tuple(str(x).strip() for x in (include_paths or ()) if str(x).strip())
    exclude = tuple(str(x).strip() for x in (exclude_paths or ()) if str(x).strip())
    seed_url = _normalize_url(seed_url, preserve_query=preserve_query)
    seed = urlsplit(seed_url)
    seed_host = (seed.hostname or "").casefold()

    started = time.monotonic()
    queue: deque[tuple[str, int]] = deque([(seed_url, 0)])
    enqueued: set[str] = {seed_url}
    seen: set[str] = set()
    pages: list[CrawlPage] = []
    skipped = 0
    timed_out = False
    robots_cache: dict[str, RobotFileParser] = {}

    async def robots_for(url: str) -> RobotFileParser | None:
        if not respect_robots:
            return None
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        cached = robots_cache.get(origin)
        if cached is not None:
            return cached
        parser = await _robots_for(url)
        robots_cache[origin] = parser
        return parser

    async def fetch_one(url: str, depth: int) -> tuple[CrawlPage, list[str]]:
        parser = await robots_for(url)
        if parser is not None and not parser.can_fetch(DEFAULT_UA, url):
            return CrawlPage(url=url, depth=depth, error="blocked by robots.txt"), []
        try:
            record_usage("native_web_requests")
            result = await fetch_url(
                url,
                include_body=True,
                max_bytes=max_bytes_per_page,
                timeout=min(20.0, max_seconds),
                url_guard=lambda target: (
                    urlsplit(target).netloc.lower() == urlsplit(url).netloc.lower()
                    and (parser is None or parser.can_fetch(DEFAULT_UA, target))
                ),
            )
            links = extract_links(result).links if result.body_text else []
            return (
                CrawlPage(
                    url=result.final_url,
                    status_code=result.status_code,
                    sha256=result.sha256,
                    links_found=len(links),
                    depth=depth,
                    content_type=result.content_type,
                    elapsed_ms=result.elapsed_ms,
                ),
                links,
            )
        except Exception as exc:  # noqa: BLE001 -- per-page failures are returned as crawl data
            return CrawlPage(url=url, depth=depth, error=f"{type(exc).__name__}: {exc}"), []

    while queue and len(pages) < max_pages:
        if time.monotonic() - started >= max_seconds:
            timed_out = True
            break

        batch: list[tuple[str, int]] = []
        while queue and len(batch) < concurrency and len(pages) + len(batch) < max_pages:
            url, depth = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            batch.append((url, depth))
        if not batch:
            continue

        results = await asyncio.gather(*(fetch_one(url, depth) for url, depth in batch))
        for (_source_url, depth), (page, links) in zip(batch, results, strict=True):
            pages.append(page)
            if depth >= max_depth:
                continue
            for raw_link in links:
                normalized = _normalize_url(raw_link, preserve_query=preserve_query)
                parts = urlsplit(normalized)
                if parts.scheme not in {"http", "https"}:
                    skipped += 1
                    continue
                if not _same_scope(seed_host, parts.hostname, include_subdomains):
                    skipped += 1
                    continue
                if not _path_allowed(normalized, include, exclude):
                    skipped += 1
                    continue
                if normalized in enqueued:
                    continue
                enqueued.add(normalized)
                queue.append((normalized, depth + 1))

        if queue and delay_seconds > 0:
            remaining = max(0.0, max_seconds - (time.monotonic() - started))
            await asyncio.sleep(min(delay_seconds, remaining))

    return CrawlResult(
        seed_url=seed_url,
        pages=pages,
        discovered_urls=len(enqueued),
        skipped_urls=skipped,
        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        truncated=bool(queue) or timed_out or len(pages) >= max_pages,
    )


async def _robots_for(seed_url: str) -> RobotFileParser:
    parts = urlsplit(seed_url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        record_usage("native_web_requests")
        result = await fetch_url(robots_url, max_bytes=512_000, include_body=True)
        parser.parse((result.body_text or "").splitlines())
    except Exception:  # noqa: BLE001 -- unavailable robots.txt defaults to an empty policy
        parser.parse([])
    return parser
