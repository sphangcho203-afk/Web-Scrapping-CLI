import httpx
import pytest

from internet_hands import crawler, fetcher, policy


@pytest.fixture
def redirect_site(monkeypatch):
    requests = []
    settings = {"redirect": "https://www.example.com/", "robots": "User-agent: *\nAllow: /"}
    client = httpx.AsyncClient

    def respond(request):
        url = str(request.url)
        requests.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=settings["robots"] if request.url.host.startswith("www.") else "User-agent: *\nAllow: /")
        if url == "https://example.com/":
            return httpx.Response(308, headers={"location": settings["redirect"]})
        return httpx.Response(200, headers={"content-type": "text/html"}, text='<h1>Price</h1><p>$20</p><a href="/pricing">Pricing</a>')

    monkeypatch.setattr(fetcher.httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(policy, "_DNS_CACHE", {})
    monkeypatch.setattr(policy.socket, "getaddrinfo", lambda host, port, **_: [(2, 1, 6, "", ("93.184.216.34", port))])
    return requests, settings


async def test_canonical_www_redirect_and_relative_links_are_crawled(redirect_site):
    requests, _ = redirect_site
    result = await crawler.crawl("https://example.com/", max_pages=2, delay_seconds=0, include_content=True)
    assert len(result.pages) == 2
    assert result.pages[0].url == "https://www.example.com/"
    assert result.pages[0].text and "$20" in result.pages[0].text
    assert "https://www.example.com/pricing" in requests
    assert "https://www.example.com/robots.txt" in requests


async def test_redirect_destination_robots_is_checked_before_page_request(redirect_site):
    requests, settings = redirect_site
    settings["robots"] = "User-agent: *\nDisallow: /"
    result = await crawler.crawl("https://example.com/", max_pages=1)
    assert result.pages[0].error
    assert "https://www.example.com/" not in requests


@pytest.mark.parametrize("destination", ["https://evil.example.net/", "https://www.example.com:8443/", "http://www.example.com/", "https://example.com.evil.net/"])
async def test_redirect_cannot_escape_host_port_or_transport_scope(redirect_site, destination):
    requests, settings = redirect_site
    settings["redirect"] = destination
    result = await crawler.crawl("https://example.com/", max_pages=1)
    assert result.pages[0].error
    assert destination not in requests


async def test_canonical_hostname_resolving_private_is_blocked(redirect_site, monkeypatch):
    requests, _ = redirect_site
    monkeypatch.setattr(policy.socket, "getaddrinfo", lambda host, port, **_: [(2, 1, 6, "", ("10.0.0.1" if host.startswith("www.") else "93.184.216.34", port))])
    result = await crawler.crawl("https://example.com/", max_pages=1)
    assert result.pages[0].error and "non-public" in result.pages[0].error
    assert "https://www.example.com/" not in requests
