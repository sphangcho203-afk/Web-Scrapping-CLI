import asyncio
import time

import httpx
import pytest

from internet_hands import crawler, fetcher, policy
from internet_hands.execution_meter import (
    execution_usage_snapshot,
    reset_execution_meter,
    start_execution_meter,
)

pytest_plugins = ["test_crawl_runs"]


def xml(kind, urls):
    child = "url" if kind == "urlset" else "sitemap"
    return f'<{kind} xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(
        f"<{child}><loc>{url}</loc></{child}>" for url in urls) + f"</{kind}>"


@pytest.fixture
def site(monkeypatch):
    requests, responses = [], {
        "https://example.com/robots.txt": (200, "text/plain", "User-agent: *\nAllow: /\nSitemap: https://example.com/index.xml"),
        "https://example.com/": (200, "text/html", "<p>Home</p>"),
        "https://example.com/index.xml": (200, "application/xml", xml("sitemapindex", ["https://example.com/pages.xml"])),
        "https://example.com/pages.xml": (200, "application/xml", xml("urlset", ["https://example.com/hidden", "https://example.com/hidden#again"])),
    }
    client = httpx.AsyncClient

    async def respond(request):
        await asyncio.sleep(0)  # Keep policy requests genuinely in flight during concurrent fetches.
        url = str(request.url)
        requests.append(url)
        value = responses.get(url, (200, "text/html", "<p>Hidden content</p>"))
        if isinstance(value, dict):
            return httpx.Response(308, headers=value)
        status, kind, body = value
        return httpx.Response(status, headers={"content-type": kind}, text=body)

    monkeypatch.setattr(fetcher.httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(respond), **kw))
    monkeypatch.setattr(policy, "_DNS_CACHE", {})
    monkeypatch.setattr(policy.socket, "getaddrinfo", lambda host, port, **_: [(2, 1, 6, "", ("93.184.216.34", port))])
    return requests, responses


async def test_index_discovers_unlinked_pages_once_and_meters_requests(site):
    requests, _ = site
    token = start_execution_meter()
    try:
        result = await crawler.crawl("https://example.com/", discover_sitemaps=True, include_content=True, delay_seconds=0)
        assert [p.url for p in result.pages] == ["https://example.com/", "https://example.com/hidden"]
        assert result.pages[1].text == "Hidden content"
        assert result.sitemap_documents == 2 and result.sitemap_urls == 1
        assert not result.sitemap_errors and not result.truncated
        assert requests.count("https://example.com/hidden") == 1
        assert execution_usage_snapshot()["counters"]["native_web_requests"] == 5
    finally:
        reset_execution_meter(token)


async def test_default_and_zero_depth_do_not_fetch_sitemaps(site):
    requests, _ = site
    await crawler.crawl("https://example.com/", delay_seconds=0)
    await crawler.crawl("https://example.com/", discover_sitemaps=True, max_depth=0, delay_seconds=0)
    assert not any(url.endswith(".xml") for url in requests)


async def test_fallback_filters_scope_paths_and_robots(site):
    requests, responses = site
    responses["https://example.com/robots.txt"] = (200, "text/plain", "User-agent: *\nDisallow: /docs/private")
    responses["https://example.com/sitemap.xml"] = (200, "application/xml", xml("urlset", [
        "https://example.com/docs/ok", "https://example.com/docs/private", "https://example.com/logout",
        "https://evil.example.net/docs/ok", "http://example.com/docs/down", "https://example.com:8443/docs/port",
        "https://example.com/docs/file.png", "https://example.com/blog/skip"]))
    result = await crawler.crawl("https://example.com/", discover_sitemaps=True,
        include_paths=["/docs/*"], exclude_paths=["/logout*"], delay_seconds=0)
    assert [p.url for p in result.pages] == ["https://example.com/", "https://example.com/docs/ok", "https://example.com/docs/private"]
    assert result.pages[-1].error == "blocked by robots.txt"
    assert "https://example.com/docs/private" not in requests
    assert not any("evil" in url or ":8443" in url or url.startswith("http:") for url in requests)


@pytest.mark.parametrize("target", ["https://evil.example.net/map.xml", "http://example.com/map.xml", "https://example.com:8443/map.xml"])
async def test_sitemap_redirect_cannot_escape_scope(site, target):
    requests, responses = site
    responses["https://example.com/index.xml"] = {"location": target}
    result = await crawler.crawl("https://example.com/", discover_sitemaps=True, delay_seconds=0)
    assert target not in requests and result.sitemap_errors
    assert result.pages[0].status_code == 200


async def test_sitemap_redirect_checks_destination_robots(site):
    requests, responses = site
    responses["https://example.com/index.xml"] = {"location": "https://www.example.com/map.xml"}
    responses["https://www.example.com/robots.txt"] = (200, "text/plain", "User-agent: *\nDisallow: /map.xml")
    result = await crawler.crawl("https://example.com/", discover_sitemaps=True, delay_seconds=0)
    assert "https://www.example.com/map.xml" not in requests and result.sitemap_errors


async def test_sitemap_private_dns_is_blocked_before_network(site, monkeypatch):
    requests, responses = site
    responses["https://example.com/index.xml"] = {"location": "https://www.example.com/map.xml"}
    monkeypatch.setattr(policy.socket, "getaddrinfo", lambda host, port, **_: [(2, 1, 6, "", (
        "10.0.0.1" if host.startswith("www.") else "93.184.216.34", port))])
    result = await crawler.crawl("https://example.com/", discover_sitemaps=True, delay_seconds=0)
    assert "https://www.example.com/map.xml" not in requests and result.sitemap_errors
    assert result.pages[0].status_code == 200


async def test_concurrent_subdomain_pages_share_robots_request(site):
    requests, responses = site
    responses["https://example.com/"] = (200, "text/html", '<a href="https://docs.example.com/a">A</a><a href="https://docs.example.com/b">B</a>')
    responses["https://docs.example.com/robots.txt"] = (200, "text/plain", "User-agent: *\nAllow: /")
    result = await crawler.crawl("https://example.com/", include_subdomains=True, concurrency=2, delay_seconds=0)
    assert len(result.pages) == 3
    assert requests.count("https://docs.example.com/robots.txt") == 1


async def test_sitemap_byte_and_location_limits(site):
    _, responses = site
    responses["https://example.com/index.xml"] = (200, "application/xml", "x" * 512001)
    result = await crawler.crawl("https://example.com/", discover_sitemaps=True, delay_seconds=0)
    assert result.sitemap_errors and len(result.pages) == 1
    responses["https://example.com/index.xml"] = (200, "application/xml", xml("urlset", [f"https://example.com/{i}" for i in range(1500)]))
    result = await crawler.crawl("https://example.com/", discover_sitemaps=True, max_pages=1, delay_seconds=0)
    assert result.sitemap_truncated and result.frontier_truncated and result.discovered_urls == 1000


async def test_discovery_timeout_preserves_seed_capture(site, monkeypatch):
    original = crawler.fetch_url

    async def slow(url, **kwargs):
        if url.endswith(".xml"):
            await asyncio.sleep(3)
        return await original(url, **kwargs)

    monkeypatch.setattr(crawler, "fetch_url", slow)
    started = time.monotonic()
    result = await crawler.crawl("https://example.com/", discover_sitemaps=True, max_seconds=1, delay_seconds=0)
    assert time.monotonic() - started < 1.6
    assert result.pages[0].status_code == 200 and result.sitemap_truncated and result.truncated


def test_job_api_rejects_non_boolean_discovery():
    from fastapi import HTTPException

    from internet_hands.crawl_run_api import crawl_arguments

    assert crawl_arguments({"url": "https://example.com", "discover_sitemaps": True})["discover_sitemaps"] is True
    assert "discover_sitemaps" not in crawl_arguments({"url": "https://example.com"})
    assert crawl_arguments({"url": "https://example.com", "discover_sitemaps": False}) == crawl_arguments({"url": "https://example.com"})
    with pytest.raises(HTTPException):
        crawl_arguments({"url": "https://example.com", "discover_sitemaps": "yes"})


async def test_owned_worker_persists_sitemap_output_progress_and_metering(site, runs):
    from internet_hands.crawl_run_api import crawl_arguments
    from internet_hands.crawl_run_worker import dispatch_run
    from internet_hands.datasets import DatasetStore

    jobs, identity = runs
    row = jobs.create(identity, "sitemap-worker", crawl_arguments({"url": "https://example.com/", "discover_sitemaps": True}))
    assert (await dispatch_run(jobs))["processed"] == 1
    current = jobs.get(identity.user_id, row["id"])
    assert current["status"] == "completed"
    assert current["progress"]["sitemap_documents"] == 2 and current["progress"]["sitemap_urls"] == 1
    assert current["credits_charged"] > 0
    dataset = DatasetStore(jobs.control).get(identity.user_id, current["dataset_id"])
    assert [r["url"] for r in dataset["rows"]] == ["https://example.com/", "https://example.com/hidden"]
    assert dataset["output"]["sitemap_documents"] == 2
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT measured_usage FROM ih_crawl_runs WHERE id=%s", (row["id"],))
        assert cur.fetchone()["measured_usage"]["counters"]["native_web_requests"] == 5


def test_canonical_seed_subdomain_scope():
    assert crawler._url_in_scope("https://www.example.com/", "https://docs.example.com/a", True)
    assert not crawler._url_in_scope("https://www.example.com/", "https://docs.example.com/a", False)


async def test_native_tool_exposes_and_executes_sitemap_control(site):
    from internet_hands.native_web_provider import NativeWebToolProvider

    provider = NativeWebToolProvider()
    result = await provider.execute("crawl", {"url": "https://example.com/", "discover_sitemaps": True})
    assert result["data"]["sitemap_urls"] == 1
    assert len(result["data"]["pages"]) == 2


@pytest.mark.parametrize("body", ["<broken", '<!DOCTYPE urlset [<!ENTITY x "https://example.com/hidden">]><urlset><url><loc>&x;</loc></url></urlset>', '<html><url><loc>https://example.com/hidden</loc></url></html>'])
async def test_bad_xml_preserves_seed_and_reports_discovery_error(site, body):
    _, responses = site
    responses["https://example.com/index.xml"] = (200, "application/xml", body)
    result = await crawler.crawl("https://example.com/", discover_sitemaps=True, delay_seconds=0)
    assert len(result.pages) == 1 and result.sitemap_errors and result.pages[0].status_code == 200


async def test_index_cycles_and_fanout_are_bounded(site):
    requests, responses = site
    responses["https://example.com/index.xml"] = (200, "application/xml", xml("sitemapindex",
        ["https://example.com/index.xml"] + [f"https://example.com/maps/{i}.xml" for i in range(100)]))
    for i in range(100):
        responses[f"https://example.com/maps/{i}.xml"] = (200, "application/xml", xml("urlset", [f"https://example.com/page/{i}"]))
    result = await crawler.crawl("https://example.com/", discover_sitemaps=True, delay_seconds=0)
    assert result.sitemap_documents == 8 and result.sitemap_truncated
    assert sum(url.endswith(".xml") for url in requests) == 8


class StopWorker(BaseException):
    pass


async def test_checkpoint_restores_sitemap_frontier_without_rediscovery(site):
    requests, _ = site
    saved = None

    async def checkpoint(result, frontier):
        nonlocal saved
        saved = result, frontier
        raise StopWorker()

    with pytest.raises(StopWorker):
        await crawler.crawl("https://example.com/", discover_sitemaps=True, delay_seconds=0, on_checkpoint=checkpoint)
    requests.clear()
    result = await crawler.crawl("https://example.com/", discover_sitemaps=True, delay_seconds=0, resume_checkpoint=saved)
    assert len(result.pages) == 2 and result.sitemap_urls == 1 and result.sitemap_documents == 2
    assert not any(url.endswith(".xml") or url == "https://example.com/" for url in requests)
    with pytest.raises(ValueError, match="controls"):
        await crawler.crawl("https://example.com/", resume_checkpoint=saved)


async def test_sync_frontier_is_bounded(site):
    _, responses = site
    responses["https://example.com/"] = (200, "text/html", "".join(f'<a href="/item/{i}">Item</a>' for i in range(1500)))
    result = await crawler.crawl("https://example.com/", max_pages=1, delay_seconds=0)
    assert result.discovered_urls == 1000 and result.frontier_truncated


async def test_inflight_robots_respects_total_time_budget(site, monkeypatch):
    original = crawler._robots_for

    async def slow(url):
        await asyncio.sleep(3)
        return await original(url)

    monkeypatch.setattr(crawler, "_robots_for", slow)
    started = time.monotonic()
    result = await crawler.crawl("https://example.com/", max_seconds=1, delay_seconds=0)
    assert time.monotonic() - started < 1.6
    assert result.truncated and "time budget" in result.pages[0].error


async def test_exhausted_single_page_site_is_not_truncated(site):
    result = await crawler.crawl("https://example.com/", max_pages=1, delay_seconds=0)
    assert not result.truncated
