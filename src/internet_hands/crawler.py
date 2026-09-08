from __future__ import annotations

import asyncio
from collections import deque
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .fetcher import DEFAULT_UA, extract_links, fetch_url
from .models import CrawlPage, CrawlResult
from .policy import validate_public_http_url


async def crawl(
    seed_url: str,
    *,
    max_pages: int = 25,
    delay_seconds: float = 0.35,
    respect_robots: bool = True,
) -> CrawlResult:
    validate_public_http_url(seed_url)
    if max_pages < 1 or max_pages > 500:
        raise ValueError("max_pages must be between 1 and 500")

    seed = urlsplit(seed_url)
    origin = (seed.scheme, seed.hostname, seed.port)
    queue: deque[str] = deque([seed_url])
    seen: set[str] = set()
    pages: list[CrawlPage] = []
    robots = await _robots_for(seed_url) if respect_robots else None

    while queue and len(pages) < max_pages:
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)

        if robots is not None and not robots.can_fetch(DEFAULT_UA, url):
            pages.append(CrawlPage(url=url, error="blocked by robots.txt"))
            continue

        try:
            result = await fetch_url(url, include_body=True)
            links = extract_links(result).links if result.body_text else []
            pages.append(
                CrawlPage(
                    url=result.final_url,
                    status_code=result.status_code,
                    sha256=result.sha256,
                    links_found=len(links),
                )
            )
            for link in links:
                parts = urlsplit(link)
                if (parts.scheme, parts.hostname, parts.port) == origin and link not in seen:
                    queue.append(link)
        except Exception as exc:  # noqa: BLE001 -- record per-page failures
            pages.append(CrawlPage(url=url, error=f"{type(exc).__name__}: {exc}"))

        if queue and delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

    return CrawlResult(seed_url=seed_url, pages=pages)


async def _robots_for(seed_url: str) -> RobotFileParser:
    parts = urlsplit(seed_url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        result = await fetch_url(robots_url, max_bytes=512_000, include_body=True)
        parser.parse((result.body_text or "").splitlines())
    except Exception:  # noqa: BLE001 -- robots retrieval failure is non-fatal
        # Fail open when robots cannot be retrieved; caller still remains bounded and same-origin.
        parser.parse([])
    return parser
