from datetime import UTC, datetime

import pytest

from internet_hands import public_data_provider as module
from internet_hands.capability_economics import estimate_call, settle_measured_cost
from internet_hands.capability_packs import CapabilityRegistry
from internet_hands.execution_meter import (
    execution_usage_snapshot,
    reset_execution_meter,
    start_execution_meter,
)
from internet_hands.models import FetchResult
from internet_hands.tool_mesh import ToolMesh


def fetched(body, mime="text/html", url="https://source.example/", status=200):
    return FetchResult(request_url=url, final_url=url, status_code=status, headers={}, content_type=mime,
                       content_length=len(body.encode()), sha256="abc", elapsed_ms=1,
                       captured_at=datetime.now(UTC), body_text=body)


@pytest.mark.parametrize(("body", "mime", "key", "expected"), [
    ('{"items":[{"id":7}]}', "application/json", "format", "json"),
    ('name,score\nAda,10\n', "text/csv", "rows", [["name", "score"], ["Ada", "10"]]),
    ('<rss><channel><item><title>Update</title><link>https://source.example/news</link></item></channel></rss>', "application/rss+xml", "format", "feed"),
    ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Update</title><link href="/news"/></entry></feed>', "application/atom+xml", "format", "feed"),
    ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://source.example/news</loc></url></urlset>', "application/xml", "format", "sitemap"),
])
def test_structured_formats(body, mime, key, expected):
    result = module.structured_document(fetched(body, mime))
    assert result[key] == expected
    assert result["source_url"] == "https://source.example/"
    assert result["sha256"] == "abc"
    assert result["captured_at"]


def test_html_tables_jsonld_published_interfaces_and_safe_links():
    html = '''<html><head><title>Scores</title><link type="application/rss+xml" href="/feed"/>
    <script type="application/ld+json">{"@type":"Dataset","name":"Scores"}</script></head>
    <body><h1>Scores</h1><table><tr><th>Team</th><th>Score</th></tr><tr><td>A</td><td>3</td></tr></table>
    <a href="/next#part">Next</a><a href="https://user:password@elsewhere.example/">bad</a></body></html>'''
    result = module.structured_document(fetched(html))
    assert result["title"] == "Scores"
    assert result["tables"][0] == [["Team", "Score"], ["A", "3"]]
    assert result["json_ld"][0]["@type"] == "Dataset"
    assert result["interfaces"][0]["url"] == "https://source.example/feed"
    assert result["links"] == ["https://source.example/next"]


@pytest.mark.parametrize("body", ['<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><x>&x;</x>', '<!ENTITY x "x"><x/>'])
def test_xml_rejects_entities(body):
    with pytest.raises(ValueError, match="DTD"):
        module.structured_document(fetched(body, "application/xml"))


@pytest.mark.parametrize("args", [{"urls": []}, {"urls": ["https://x.example"], "max_pages": 21},
                                  {"urls": ["https://x.example"], "max_pages": True},
                                  {"urls": ["https://user:pass@x.example"]},
                                  {"urls": ["https://x.example"], "headers": {}}])
def test_work_budgets_reject_invalid_inputs(args):
    with pytest.raises(ValueError):
        module.request_budget("research", args)
    assert not estimate_call("mesh_execute", {"ref": "publicdata:research", "arguments": args}, "free").allowed


async def test_research_scope_robots_partial_evidence_and_actual_charge(monkeypatch):
    requests = []
    async def fetch(url, **kwargs):
        requests.append(url)
        assert kwargs["max_bytes"] == 1_000_000 and kwargs["max_redirects"] == 3
        if url.endswith("robots.txt"):
            return fetched("User-agent: *\nDisallow: /private", "text/plain", url)
        if url.endswith("missing"):
            return fetched("not found", "text/plain", url, 404)
        return fetched('<html><p>Public scores: A wins.</p><a href="/private">private</a><a href="/missing">missing</a><a href="https://outside.example/">outside</a></html>', url=url)
    monkeypatch.setattr(module, "fetch_url", fetch)
    args = {"urls": ["https://source.example/"], "query": "scores", "max_pages": 5}
    call = {"ref": "publicdata:research", "arguments": args}
    quote = estimate_call("mesh_execute", call, "free")
    token = start_execution_meter()
    try:
        result = await ToolMesh([module.PublicDataProvider()]).execute(call["ref"], args)
        usage = execution_usage_snapshot()
    finally:
        reset_execution_meter(token)
    assert result["status"] == "completed"
    data = result["data"]
    assert data["pages_collected"] == 1 and data["partial"] is True
    assert len(data["errors"]) == 2
    assert data["evidence"][0]["matched_terms"] == ["scores"]
    assert not any("outside" in url or "private" in url for url in requests)
    assert usage["counters"]["public_data_requests"] == len(requests) == 3
    assert quote.credits == 32
    assert settle_measured_cost("mesh_execute", call, "free", reserved_credits=quote.credits, execution_usage=usage) == 11


async def test_time_budget_returns_partial_and_does_not_claim_completion(monkeypatch):
    import asyncio
    async def fetch(*args, **kwargs):
        await asyncio.sleep(1)
    monkeypatch.setattr(module, "fetch_url", fetch)
    result = await module.research({"urls": ["https://source.example/"]}, timeout=0.01)
    assert result["stop_reason"] == "time_budget" and result["partial"] is True
    assert result["evidence"] == []


async def test_no_sources_is_failed_and_private_destination_uses_safe_fetcher(monkeypatch):
    from internet_hands.policy import PolicyError
    async def fetch(url, **kwargs):
        raise PolicyError("Destination is not public")
    monkeypatch.setattr(module, "fetch_url", fetch)
    result = await ToolMesh([module.PublicDataProvider()]).execute("publicdata:research", {"urls": ["http://127.0.0.1/"]})
    assert result["status"] == "failed"
    assert result["data"]["pages_collected"] == 0


async def test_semantic_research_forwards_seed_urls_and_quotes_page_budget(monkeypatch):
    async def fetch(url, **kwargs):
        if url.endswith("robots.txt"):
            return fetched("User-agent: *\nAllow: /", "text/plain", url)
        return fetched("Public match results", "text/plain", url)

    monkeypatch.setattr(module, "fetch_url", fetch)
    mesh = ToolMesh([module.PublicDataProvider()])
    registry = CapabilityRegistry(mesh, module.build_public_data_capabilities())
    monkeypatch.setattr("internet_hands.tool_mcp.get_capability_registry", lambda: registry)
    args = {"urls": ["https://source.example/results"], "query": "match", "max_pages": 2}
    quote = estimate_call("mesh_capability_execute", {"capability": "web.public.research", "arguments": args}, "free")
    assert quote.allowed and quote.credits == 16
    result = await registry.execute("web.public.research", args)
    assert result["selected"] == "publicdata:research"
    assert result["execution"]["data"]["evidence"][0]["source_url"] == args["urls"][0]


async def test_fetcher_checks_redirect_scope_before_requesting_target(monkeypatch):
    from types import SimpleNamespace
    from urllib.parse import urlsplit

    import httpx

    from internet_hands import fetcher
    from internet_hands.policy import PolicyError

    requests = []
    def handle(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://outside.example/private"})
    client_type = httpx.AsyncClient
    monkeypatch.setattr(fetcher.httpx, "AsyncClient", lambda **kwargs: client_type(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setattr(fetcher, "resolve_public_http_url", lambda url: SimpleNamespace(addresses=("93.184.216.34",)))
    with pytest.raises(PolicyError, match="crawl scope"):
        await fetcher.fetch_url("https://source.example/", url_guard=lambda url: urlsplit(url).hostname == "source.example")
    assert requests == ["https://source.example/"]


async def test_research_passes_robots_rules_to_redirect_guard(monkeypatch):
    async def fetch(url, **kwargs):
        if url.endswith("robots.txt"):
            assert not kwargs["url_guard"]("https://elsewhere.example/robots.txt")
            return fetched("User-agent: *\nDisallow: /private", "text/plain", url)
        assert kwargs["url_guard"]("https://source.example/public")
        assert not kwargs["url_guard"]("https://source.example/private")
        assert not kwargs["url_guard"]("https://outside.example/")
        return fetched("Public content", "text/plain", url)
    monkeypatch.setattr(module, "fetch_url", fetch)
    result = await module.research({"urls": ["https://source.example/"]}, timeout=2)
    assert result["pages_collected"] == 1
