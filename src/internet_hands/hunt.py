from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from .crawler import _robots_for
from .extractor import extract_document
from .fetcher import DEFAULT_UA, fetch_url
from .policy import validate_public_http_url
from .storage import DEFAULT_DB, Store
from .web_search import SearchKind, brave_search

TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
}


class HuntScope(StrEnum):
    ORIGIN = "origin"
    HOST = "host"
    WEB = "web"


@dataclass(slots=True)
class HuntTask:
    url: str
    depth: int
    parent: str | None = None


@dataclass(slots=True)
class HuntPage:
    url: str
    depth: int
    parent: str | None
    status_code: int | None = None
    content_type: str | None = None
    sha256: str | None = None
    title: str | None = None
    links_found: int = 0
    indexed: bool = False
    duplicate_content: bool = False
    error: str | None = None


class HostLimiter:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = max(delay_seconds, 0.0)
        self._locks: dict[str, asyncio.Lock] = {}
        self._next_at: dict[str, float] = {}

    async def run(self, url: str, operation):
        host = (urlsplit(url).hostname or "").lower()
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            wait = self._next_at.get(host, 0.0) - now
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                return await operation()
            finally:
                self._next_at[host] = time.monotonic() + self.delay_seconds


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("Only absolute HTTP(S) URLs can enter the hunt frontier")

    scheme = parts.scheme.lower()
    host = parts.hostname.lower().rstrip(".")
    port = parts.port
    default_port = 443 if scheme == "https" else 80
    netloc = host if port in {None, default_port} else f"{host}:{port}"

    path = parts.path or "/"
    pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_QUERY_KEYS:
            continue
        pairs.append((key, value))
    pairs.sort()
    query = urlencode(pairs, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def _same_scope(seed_url: str, candidate: str, scope: HuntScope) -> bool:
    seed = urlsplit(seed_url)
    target = urlsplit(candidate)
    if scope == HuntScope.WEB:
        return True
    if scope == HuntScope.HOST:
        return (seed.hostname or "").lower() == (target.hostname or "").lower()
    seed_port = seed.port or (443 if seed.scheme == "https" else 80)
    target_port = target.port or (443 if target.scheme == "https" else 80)
    return (
        seed.scheme.lower(),
        (seed.hostname or "").lower(),
        seed_port,
    ) == (
        target.scheme.lower(),
        (target.hostname or "").lower(),
        target_port,
    )


def _collect_search_urls(payload: Any, *, limit: int) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()

    def walk(value: Any) -> None:
        if len(output) >= limit:
            return
        if isinstance(value, dict):
            candidate = value.get("url")
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                try:
                    normalized = canonicalize_url(candidate)
                except ValueError:
                    normalized = ""
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    output.append(normalized)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(payload)
    return output[:limit]


async def search_seeds(query: str, *, count: int = 10) -> list[str]:
    record = await brave_search(query, kind=SearchKind.WEB, count=count)
    response = (record.get("data") or {}).get("response") or {}
    return _collect_search_urls(response, limit=count)


async def hunt(
    seeds: list[str],
    *,
    scope: HuntScope = HuntScope.ORIGIN,
    max_pages: int = 100,
    max_depth: int = 3,
    max_domains: int = 20,
    concurrency: int = 8,
    per_host_delay: float = 0.35,
    respect_robots: bool = True,
    index: bool = True,
    db_path: Path = DEFAULT_DB,
) -> dict[str, Any]:
    if not seeds:
        raise ValueError("at least one seed URL is required")
    if not 1 <= max_pages <= 5000:
        raise ValueError("max_pages must be between 1 and 5000")
    if not 0 <= max_depth <= 12:
        raise ValueError("max_depth must be between 0 and 12")
    if not 1 <= max_domains <= 500:
        raise ValueError("max_domains must be between 1 and 500")
    if not 1 <= concurrency <= 64:
        raise ValueError("concurrency must be between 1 and 64")

    normalized_seeds: list[str] = []
    for raw in seeds:
        normalized = canonicalize_url(raw)
        validate_public_http_url(normalized)
        if normalized not in normalized_seeds:
            normalized_seeds.append(normalized)

    frontier: deque[HuntTask] = deque(HuntTask(url=seed, depth=0) for seed in normalized_seeds)
    queued: set[str] = set(normalized_seeds)
    visited: set[str] = set()
    content_hashes: set[str] = set()
    domains: set[str] = {
        (urlsplit(seed).hostname or "").lower() for seed in normalized_seeds
    }
    robots_cache: dict[str, RobotFileParser | None] = {}
    limiter = HostLimiter(per_host_delay)
    store = Store(db_path) if index else None
    pages: list[HuntPage] = []

    async def robots_for(url: str) -> RobotFileParser | None:
        if not respect_robots:
            return None
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in robots_cache:
            try:
                robots_cache[origin] = await _robots_for(url)
            except Exception:  # noqa: BLE001 -- robots failures remain non-fatal
                robots_cache[origin] = None
        return robots_cache[origin]

    async def process(task: HuntTask) -> tuple[HuntPage, list[str]]:
        page = HuntPage(url=task.url, depth=task.depth, parent=task.parent)
        try:
            robots = await robots_for(task.url)
            if robots is not None and not robots.can_fetch(DEFAULT_UA, task.url):
                page.error = "blocked by robots.txt"
                return page, []

            async def do_fetch():
                return await fetch_url(task.url, include_body=True)

            result = await limiter.run(task.url, do_fetch)
            document = extract_document(result)
            page.url = result.final_url
            page.status_code = result.status_code
            page.content_type = result.content_type
            page.sha256 = result.sha256
            page.title = document.title
            page.links_found = len(document.links)

            if result.sha256 in content_hashes:
                page.duplicate_content = True
                return page, []
            content_hashes.add(result.sha256)

            if store is not None:
                store.save_fetch(result, document)
                page.indexed = True

            return page, document.links
        except Exception as exc:  # noqa: BLE001 -- individual page failures are data
            page.error = f"{type(exc).__name__}: {exc}"
            return page, []

    while frontier and len(pages) < max_pages:
        batch: list[HuntTask] = []
        used_hosts: set[str] = set()
        deferred: deque[HuntTask] = deque()

        while frontier and len(batch) < concurrency:
            task = frontier.popleft()
            if task.url in visited:
                continue
            host = (urlsplit(task.url).hostname or "").lower()
            if host in used_hosts:
                deferred.append(task)
                continue
            visited.add(task.url)
            used_hosts.add(host)
            batch.append(task)

        frontier.extendleft(reversed(deferred))
        if not batch:
            task = frontier.popleft()
            if task.url not in visited:
                visited.add(task.url)
                batch.append(task)

        results = await asyncio.gather(*(process(task) for task in batch))
        for task, (page, links) in zip(batch, results, strict=True):
            pages.append(page)
            if len(pages) >= max_pages or task.depth >= max_depth or page.error:
                continue

            anchor_seed = normalized_seeds[0]
            if scope != HuntScope.WEB:
                anchor_seed = task.url

            for raw_link in links:
                if len(queued) >= max_pages * 20:
                    break
                try:
                    link = canonicalize_url(raw_link)
                    if not _same_scope(anchor_seed, link, scope):
                        continue
                    validate_public_http_url(link)
                except (ValueError, OSError):
                    continue

                host = (urlsplit(link).hostname or "").lower()
                if host not in domains:
                    if len(domains) >= max_domains:
                        continue
                    domains.add(host)
                if link in queued or link in visited:
                    continue
                queued.add(link)
                frontier.append(HuntTask(url=link, depth=task.depth + 1, parent=page.url))

    return {
        "seeds": normalized_seeds,
        "scope": scope.value,
        "limits": {
            "max_pages": max_pages,
            "max_depth": max_depth,
            "max_domains": max_domains,
            "concurrency": concurrency,
            "per_host_delay": per_host_delay,
            "respect_robots": respect_robots,
        },
        "summary": {
            "pages": len(pages),
            "successful": sum(1 for page in pages if page.status_code is not None and not page.error),
            "errors": sum(1 for page in pages if page.error),
            "duplicates": sum(1 for page in pages if page.duplicate_content),
            "domains": len(domains),
            "indexed": sum(1 for page in pages if page.indexed),
        },
        "pages": [page.__dict__ for page in pages],
    }
