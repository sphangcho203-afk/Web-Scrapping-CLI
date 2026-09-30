from datetime import UTC, datetime
from urllib.robotparser import RobotFileParser

import pytest

from internet_hands import crawler
from internet_hands.models import FetchResult


@pytest.fixture
def site(monkeypatch):
    calls = []
    bodies = {
        "https://example.com/": '<p>Seed content</p><a href="/a">A</a><a href="/b">B</a>',
        "https://example.com/a": '<p>A content</p><a href="/b">B</a>',
        "https://example.com/b": '<p>B content</p>',
    }

    async def fetch(url, **kwargs):
        calls.append(url)
        body = bodies[url]
        return FetchResult(request_url=url, final_url=url, status_code=200, headers={},
            content_type="text/html", content_length=len(body), sha256="a" * 64,
            elapsed_ms=1, captured_at=datetime.now(UTC), body_text=body)

    async def robots(url):
        parser = RobotFileParser()
        parser.parse(["User-agent: *", "Allow: /"])
        return parser

    monkeypatch.setattr(crawler, "fetch_url", fetch)
    monkeypatch.setattr(crawler, "_robots_for", robots)
    monkeypatch.setattr(crawler, "validate_public_http_url", lambda _: None)
    return calls, bodies


class StopWorker(BaseException):
    pass


async def test_resume_keeps_captured_page_and_fetches_only_pending(site):
    calls, _ = site
    saved = None

    async def checkpoint(result, frontier):
        nonlocal saved
        saved = (result, frontier)
        raise StopWorker()

    with pytest.raises(StopWorker):
        await crawler.crawl("https://example.com/", include_content=True, concurrency=1,
                            delay_seconds=0, on_checkpoint=checkpoint)
    assert calls == ["https://example.com/"]
    result = await crawler.crawl("https://example.com/", include_content=True, concurrency=1,
                                delay_seconds=0, resume_checkpoint=saved)
    assert calls == ["https://example.com/", "https://example.com/a", "https://example.com/b"]
    assert result.pages[0].text.startswith("Seed content")
    assert len(result.pages) == 3 and result.discovered_urls == 3


async def test_resume_enforces_original_content_and_time_budgets(site):
    calls, _ = site
    saved = None

    async def checkpoint(result, frontier):
        nonlocal saved
        saved = (result, frontier)
        raise StopWorker()

    with pytest.raises(StopWorker):
        await crawler.crawl("https://example.com/", include_content=True, max_content_bytes=8,
                            delay_seconds=0, on_checkpoint=checkpoint)
    result = await crawler.crawl("https://example.com/", include_content=True, max_content_bytes=8,
                                delay_seconds=0, resume_checkpoint=saved)
    assert sum(len((page.text or "").encode()) for page in result.pages) == 8
    assert result.content_bytes == 8 and result.content_truncated
    saved[0].duration_ms = 120000
    calls.clear()
    result = await crawler.crawl("https://example.com/", include_content=True, max_content_bytes=8,
                                delay_seconds=0, resume_checkpoint=saved)
    assert calls == [] and result.truncated


async def test_changed_controls_or_foreign_frontier_fail_before_fetch(site):
    calls, _ = site
    saved = None

    async def checkpoint(result, frontier):
        nonlocal saved
        saved = (result, frontier)
        raise StopWorker()

    with pytest.raises(StopWorker):
        await crawler.crawl("https://example.com/", delay_seconds=0, on_checkpoint=checkpoint)
    calls.clear()
    with pytest.raises(ValueError, match="controls"):
        await crawler.crawl("https://example.com/", max_depth=1, resume_checkpoint=saved)
    saved[1].pending = [("https://foreign.example/path", 1)]
    with pytest.raises(ValueError, match="scope"):
        await crawler.crawl("https://example.com/", resume_checkpoint=saved)
    assert calls == []


async def test_frontier_fanout_is_bounded_and_truncation_explicit(site):
    _, bodies = site
    bodies["https://example.com/"] = "".join(f'<a href="/item/{i}">Item</a>' for i in range(1500))
    saved = None

    async def checkpoint(result, frontier):
        nonlocal saved
        saved = (result, frontier)
        raise StopWorker()

    with pytest.raises(StopWorker):
        await crawler.crawl("https://example.com/", max_pages=1, on_checkpoint=checkpoint)
    result, frontier = saved
    assert len(frontier.pending) == 999 and result.skipped_urls == 501
    assert result.frontier_truncated and result.truncated
    assert len(frontier.serialized().encode()) < 600000


async def test_inflight_page_can_repeat_but_committed_seed_does_not(site, monkeypatch):
    calls, _ = site
    fetch = crawler.fetch_url
    saved = None
    crashed = False

    async def checkpoint(result, frontier):
        nonlocal saved
        saved = (result, frontier)

    async def crash_inflight(url, **kwargs):
        nonlocal crashed
        result = await fetch(url, **kwargs)
        if url.endswith("/a") and not crashed:
            crashed = True
            raise StopWorker()
        return result

    monkeypatch.setattr(crawler, "fetch_url", crash_inflight)
    with pytest.raises(StopWorker):
        await crawler.crawl("https://example.com/", concurrency=1, delay_seconds=0, on_checkpoint=checkpoint)
    result = await crawler.crawl("https://example.com/", concurrency=1, delay_seconds=0, resume_checkpoint=saved)
    assert calls == ["https://example.com/", "https://example.com/a", "https://example.com/a", "https://example.com/b"]
    assert len(result.pages) == 3


async def test_robots_policy_is_refreshed_on_recovery(site, monkeypatch):
    calls, _ = site
    saved = None

    async def checkpoint(result, frontier):
        nonlocal saved
        saved = (result, frontier)
        raise StopWorker()

    with pytest.raises(StopWorker):
        await crawler.crawl("https://example.com/", delay_seconds=0, on_checkpoint=checkpoint)

    async def robots(url):
        parser = RobotFileParser()
        parser.parse(["User-agent: *", "Disallow: /a"])
        return parser

    monkeypatch.setattr(crawler, "_robots_for", robots)
    result = await crawler.crawl("https://example.com/", delay_seconds=0, resume_checkpoint=saved)
    assert calls == ["https://example.com/", "https://example.com/b"]
    assert result.pages[1].error == "blocked by robots.txt"


def test_frontier_bounds_are_utf8_bytes_and_reject_duplicate_state():
    from internet_hands.crawl_frontier import CrawlFrontier
    base = {"config_hash": "a" * 64, "completed": [], "pending": []}
    with pytest.raises(ValueError, match="bytes"):
        CrawlFrontier(**{**base, "pending": [("https://example.com/" + "é" * 2048, 1)]})
    with pytest.raises(ValueError, match="bytes"):
        CrawlFrontier(**{**base, "pending": [("https://example.com/" + "x" * 3000 + str(i), 1) for i in range(200)]})
    with pytest.raises(ValueError, match="unique"):
        CrawlFrontier(**{**base, "completed": ["https://example.com/"], "pending": [("https://example.com/", 1)]})
