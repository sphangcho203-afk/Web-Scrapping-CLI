from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import time
from collections import deque
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .crawl_frontier import MAX_FRONTIER_URL_BYTES, MAX_FRONTIER_URLS, MAX_URL_BYTES, CrawlFrontier
from .execution_meter import record_usage
from .extractor import extract_document
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
    canonical = root.removeprefix("www.")
    return host in {root, canonical, "www." + canonical} or (
        include_subdomains and host.endswith("." + root)
    )


def _url_in_scope(seed_url: str, target: str, include_subdomains: bool = False) -> bool:
    seed, candidate = urlsplit(seed_url), urlsplit(target)
    if candidate.scheme not in {"http", "https"}:
        return False
    if seed.scheme == "https" and candidate.scheme != "https":
        return False
    try:
        seed_port = seed.port or (443 if seed.scheme == "https" else 80)
        target_port = candidate.port or (443 if candidate.scheme == "https" else 80)
    except ValueError:
        return False
    upgrade = seed.scheme == "http" and candidate.scheme == "https" and seed_port == 80 and target_port == 443
    return (seed_port == target_port or upgrade) and _same_scope(seed.hostname or "", candidate.hostname, include_subdomains)


def _bounded_text(value: str, max_bytes: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), len(encoded) > max_bytes


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
    include_content: bool = False,
    max_content_bytes_per_page: int = 50_000,
    max_content_bytes: int = 750_000,
    on_progress: Callable[[CrawlResult], Awaitable[None]] | None = None,
    on_checkpoint: Callable[[CrawlResult, CrawlFrontier], Awaitable[None]] | None = None,
    resume_checkpoint: tuple[CrawlResult, CrawlFrontier] | None = None,
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
    if not isinstance(include_content, bool):
        raise TypeError("include_content must be a boolean")
    if type(max_content_bytes_per_page) is not int or type(max_content_bytes) is not int:
        raise TypeError("content budgets must be integers")
    if not 1 <= max_content_bytes_per_page <= 200_000:
        raise ValueError("max_content_bytes_per_page must be between 1 and 200000")
    if not 1 <= max_content_bytes <= 1_000_000:
        raise ValueError("max_content_bytes must be between 1 and 1000000")

    include = tuple(str(x).strip() for x in (include_paths or ()) if str(x).strip())
    exclude = tuple(str(x).strip() for x in (exclude_paths or ()) if str(x).strip())
    seed_url = _normalize_url(seed_url, preserve_query=preserve_query)

    resumable = on_checkpoint is not None or resume_checkpoint is not None
    controls = {
        "seed_url": seed_url, "max_pages": max_pages, "max_depth": max_depth,
        "concurrency": concurrency, "max_seconds": float(max_seconds), "respect_robots": respect_robots,
        "include_paths": list(include), "exclude_paths": list(exclude),
        "include_subdomains": include_subdomains, "preserve_query": preserve_query,
        "max_bytes_per_page": max_bytes_per_page, "include_content": include_content,
        "max_content_bytes_per_page": max_content_bytes_per_page, "max_content_bytes": max_content_bytes,
    }
    config_hash = hashlib.sha256(json.dumps(controls, sort_keys=True).encode()).hexdigest()
    if resumable and len(seed_url.encode()) > MAX_URL_BYTES:
        raise ValueError("Checkpoint URLs exceed their byte budget.")
    started = time.monotonic()
    queue: deque[tuple[str, int]] = deque([(seed_url, 0)])
    enqueued: set[str] = {seed_url}
    seen: set[str] = set()
    pages: list[CrawlPage] = []
    skipped = 0
    timed_out = False
    content_bytes = 0
    robots_cache: dict[str, RobotFileParser] = {}
    elapsed_before = 0
    frontier_truncated = False
    frontier_bytes = len(seed_url.encode())
    if resume_checkpoint is not None:
        prior, frontier = resume_checkpoint
        # Revalidate even in-memory instances: a caller may have mutated them.
        frontier = CrawlFrontier.model_validate(frontier.model_dump())
        if frontier.config_hash != config_hash or prior.seed_url != seed_url:
            raise ValueError("Checkpoint controls do not match this crawl.")
        pending_urls = [url for url, _ in frontier.pending]
        all_urls = [*frontier.completed, *pending_urls]
        if any(_normalize_url(url, preserve_query=preserve_query) != url
               or urlsplit(url).scheme not in {"http", "https"}
               or not _url_in_scope(seed_url, url, include_subdomains)
               for url in all_urls):
            raise ValueError("Checkpoint URLs are outside the crawl scope.")
        if any(depth > max_depth or not _path_allowed(url, include, exclude)
               for url, depth in frontier.pending if url != seed_url):
            raise ValueError("Checkpoint frontier violates crawl controls.")
        if (len(prior.pages) != len(frontier.completed) or len(prior.pages) > max_pages
                or seed_url not in all_urls or prior.duration_ms < 0 or prior.skipped_urls < 0
                or prior.content_bytes != sum(len((page.text or "").encode()) for page in prior.pages)
                or prior.content_bytes > max_content_bytes):
            raise ValueError("Checkpoint result exceeds crawl budgets or is inconsistent.")
        queue = deque(frontier.pending)
        seen = set(frontier.completed)
        enqueued = seen | set(pending_urls)
        pages = list(prior.pages)
        skipped, content_bytes = prior.skipped_urls, prior.content_bytes
        elapsed_before = prior.duration_ms
        frontier_truncated = frontier.truncated
        frontier_bytes = sum(len(url.encode()) for url in enqueued)

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
        nonlocal content_bytes
        parser = await robots_for(url)
        if parser is not None and not parser.can_fetch(DEFAULT_UA, url):
            return CrawlPage(url=url, depth=depth, error="blocked by robots.txt"), []

        last_hop = url
        async def redirect_allowed(target: str) -> bool:
            nonlocal last_hop
            if not _url_in_scope(url, target) or not _url_in_scope(last_hop, target):
                return False
            if target != url and not _path_allowed(target, (), exclude):
                return False
            destination_policy = await robots_for(target)
            allowed = destination_policy is None or destination_policy.can_fetch(DEFAULT_UA, target)
            if allowed:
                last_hop = target
            return allowed

        try:
            record_usage("native_web_requests")
            result = await fetch_url(
                url,
                include_body=True,
                max_bytes=max_bytes_per_page,
                timeout=min(20.0, max_seconds),
                url_guard=redirect_allowed,
            )
            links = extract_links(result).links if result.body_text else []
            page = CrawlPage(
                url=result.final_url,
                status_code=result.status_code,
                sha256=result.sha256,
                links_found=len(links),
                depth=depth,
                content_type=result.content_type,
                elapsed_ms=result.elapsed_ms,
            )
            if include_content:
                page.captured_at = result.captured_at
                content_type = (result.content_type or "").lower()
                readable = content_type.startswith("text/") or any(
                    kind in content_type for kind in ("html", "json", "xml")
                )
                if not 200 <= result.status_code < 300:
                    page.content_error = f"HTTP {result.status_code}: content was not extracted."
                elif not readable:
                    page.content_error = "This content type does not support text extraction."
                else:
                    try:
                        document = extract_document(result)
                        title, title_clipped = _bounded_text(document.title or "", 1000)
                        description, description_clipped = _bounded_text(document.description or "", 2000)
                        headings = [_bounded_text(value, 500) for value in document.headings[:40]]
                        page.title = title or None
                        page.description = description or None
                        page.headings = [value for value, _ in headings]
                        metadata_clipped = (title_clipped or description_clipped
                                            or len(document.headings) > 40
                                            or any(clipped for _, clipped in headings))
                        # No await between reading and claiming the shared budget: concurrent
                        # fetches cannot each claim the same remaining capacity.
                        allowance = min(max_content_bytes_per_page, max_content_bytes - content_bytes)
                        page.text, page.content_truncated = _bounded_text(document.text, allowance)
                        page.content_truncated = page.content_truncated or metadata_clipped
                        content_bytes += len(page.text.encode("utf-8"))
                        if not document.text:
                            page.content_error = "No readable text was found in this capture."
                    except Exception:  # noqa: BLE001 -- preserve a successful fetch on extraction failure
                        page.content_error = "Readable content could not be extracted from this capture."
            return page, links
        except Exception as exc:  # noqa: BLE001 -- per-page failures are returned as crawl data
            return CrawlPage(url=url, depth=depth, error=f"{type(exc).__name__}: {exc}"), []

    def snapshot() -> CrawlResult:
        return CrawlResult(
            seed_url=seed_url, pages=list(pages), discovered_urls=len(enqueued),
            skipped_urls=skipped, duration_ms=elapsed_before + max(0, int((time.monotonic() - started) * 1000)),
            truncated=bool(queue) or timed_out or len(pages) >= max_pages or frontier_truncated,
            frontier_truncated=frontier_truncated,
            content_bytes=content_bytes, content_truncated=any(page.content_truncated for page in pages),
        )

    while queue and len(pages) < max_pages:
        if elapsed_before / 1000 + time.monotonic() - started >= max_seconds:
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
                if not _url_in_scope(seed_url, normalized, include_subdomains):
                    skipped += 1
                    continue
                if not _path_allowed(normalized, include, exclude):
                    skipped += 1
                    continue
                if normalized in enqueued:
                    continue
                if resumable:
                    url_bytes = len(normalized.encode())
                    if (url_bytes > MAX_URL_BYTES or len(enqueued) >= MAX_FRONTIER_URLS
                            or frontier_bytes + url_bytes > MAX_FRONTIER_URL_BYTES):
                        frontier_truncated = True
                        skipped += 1
                        continue
                    frontier_bytes += url_bytes
                enqueued.add(normalized)
                queue.append((normalized, depth + 1))

        if on_checkpoint is not None:
            await on_checkpoint(snapshot(), CrawlFrontier(config_hash=config_hash,
                pending=list(queue), completed=sorted(seen), truncated=frontier_truncated))
        if on_progress is not None:
            await on_progress(snapshot())

        if queue and delay_seconds > 0:
            remaining = max(0.0, max_seconds - elapsed_before / 1000 - (time.monotonic() - started))
            await asyncio.sleep(min(delay_seconds, remaining))

    return snapshot()


async def _robots_for(seed_url: str) -> RobotFileParser:
    parts = urlsplit(seed_url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        record_usage("native_web_requests")
        result = await fetch_url(robots_url, max_bytes=512_000, include_body=True,
                                 url_guard=lambda target: _url_in_scope(robots_url, target))
        if result.status_code in {401, 403}:
            parser.parse(["User-agent: *", "Disallow: /"])
        else:
            parser.parse((result.body_text or "").splitlines() if result.status_code == 200 else [])
    except Exception:  # noqa: BLE001 -- unavailable robots.txt defaults to an empty policy
        parser.parse([])
    return parser
