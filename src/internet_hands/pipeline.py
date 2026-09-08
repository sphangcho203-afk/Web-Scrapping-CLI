from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .crawler import _robots_for
from .extractor import extract_document
from .fetcher import DEFAULT_UA, fetch_url
from .models import IndexResult, WatchRun
from .policy import validate_public_http_url
from .storage import DEFAULT_DB, Store

logger = logging.getLogger(__name__)


async def index_url(url: str, *, db_path: Path = DEFAULT_DB) -> IndexResult:
    result = await fetch_url(url, include_body=True)
    document = extract_document(result)
    store = Store(db_path)
    capture_id = store.save_fetch(result, document)
    return IndexResult(
        capture_id=capture_id,
        url=document.url,
        title=document.title,
        sha256=document.sha256,
        text_length=len(document.text),
        links_found=len(document.links),
    )


async def index_crawl(
    seed_url: str,
    *,
    db_path: Path = DEFAULT_DB,
    max_pages: int = 25,
    delay_seconds: float = 0.35,
    respect_robots: bool = True,
) -> list[IndexResult]:
    validate_public_http_url(seed_url)
    if max_pages < 1 or max_pages > 500:
        raise ValueError("max_pages must be between 1 and 500")
    seed = urlsplit(seed_url)
    origin = (seed.scheme, seed.hostname, seed.port)
    queue: deque[str] = deque([seed_url])
    seen: set[str] = set()
    output: list[IndexResult] = []
    robots: RobotFileParser | None = await _robots_for(seed_url) if respect_robots else None
    store = Store(db_path)

    while queue and len(output) < max_pages:
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        if robots is not None and not robots.can_fetch(DEFAULT_UA, url):
            continue
        try:
            result = await fetch_url(url, include_body=True)
            document = extract_document(result)
            capture_id = store.save_fetch(result, document)
            output.append(
                IndexResult(
                    capture_id=capture_id,
                    url=document.url,
                    title=document.title,
                    sha256=document.sha256,
                    text_length=len(document.text),
                    links_found=len(document.links),
                )
            )
            for link in document.links:
                parts = urlsplit(link)
                if (parts.scheme, parts.hostname, parts.port) == origin and link not in seen:
                    queue.append(link)
        except Exception as exc:  # noqa: BLE001 -- one bad page must not abort the crawl
            logger.warning("index crawl skipped %s: %s: %s", url, type(exc).__name__, exc)
        if queue and delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
    return output


async def run_due_watches(*, db_path: Path = DEFAULT_DB, limit: int = 100) -> list[WatchRun]:
    store = Store(db_path)
    runs: list[WatchRun] = []
    for job in store.due_watches(limit=limit):
        checked_at = datetime.now(UTC)
        try:
            result = await fetch_url(job.url, include_body=True)
            document = extract_document(result)
            store.save_fetch(result, document)
            changed = job.last_sha256 is None or job.last_sha256 != result.sha256
            run = WatchRun(
                watch_id=job.id,
                url=job.url,
                checked_at=checked_at,
                changed=changed,
                status_code=result.status_code,
                sha256=result.sha256,
            )
        except Exception as exc:  # noqa: BLE001 -- watch failures are persisted as events
            run = WatchRun(
                watch_id=job.id,
                url=job.url,
                checked_at=checked_at,
                changed=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        store.record_watch_run(job, run)
        runs.append(run)
    return runs
