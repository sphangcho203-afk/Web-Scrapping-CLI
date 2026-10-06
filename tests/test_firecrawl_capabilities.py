from __future__ import annotations

from internet_hands.firecrawl_capabilities import build_firecrawl_capabilities


def test_firecrawl_capability_ids_are_unique() -> None:
    capabilities = build_firecrawl_capabilities()
    ids = [capability.id for capability in capabilities]
    assert len(ids) == len(set(ids))
    assert {
        "web.fetch.page",
        "web.scrape.smart",
        "web.scrape.http",
        "web.scrape.rendered",
        "web.search.live",
        "web.research.rag",
        "web.map.site",
        "web.crawl.site",
        "web.scrape.batch",
        "web.extract.structured",
    }.issubset(ids)


def test_page_fetch_prefers_firecrawl_then_apify() -> None:
    capability = next(
        item for item in build_firecrawl_capabilities() if item.id == "web.fetch.page"
    )
    assert capability.read_only is True
    assert [candidate.ref for candidate in capability.candidates] == [
        "firecrawl:scrape",
        "apify:apify/web-fetch",
        "nativeweb:fetch",
    ]
    assert [candidate.priority for candidate in capability.candidates] == [5, 20, 40]


def test_research_prefers_firecrawl_agent_and_maps_query_to_prompt() -> None:
    capability = next(
        item for item in build_firecrawl_capabilities() if item.id == "web.research.rag"
    )
    primary = capability.candidates[0]
    fallback = capability.candidates[1]
    assert primary.ref == "firecrawl:agent"
    assert primary.argument_map == {"query": "prompt"}
    assert fallback.ref == "apify:apify/rag-web-browser"


def test_site_crawl_and_batch_are_read_only_async_capabilities() -> None:
    capabilities = {item.id: item for item in build_firecrawl_capabilities()}
    assert capabilities["web.crawl.site"].read_only is True
    assert capabilities["web.crawl.site"].candidates[0].ref == "firecrawl:crawl"
    assert capabilities["web.scrape.batch"].candidates[0].ref == "firecrawl:batch-scrape"


def test_smart_scrape_is_native_first_with_rendered_fallback() -> None:
    capabilities = {item.id: item for item in build_firecrawl_capabilities()}
    smart = capabilities["web.scrape.smart"]
    assert [candidate.ref for candidate in smart.candidates] == [
        "nativeweb:scrape",
        "firecrawl:scrape",
    ]
    assert [candidate.priority for candidate in smart.candidates] == [5, 20]
    assert smart.candidates[0].defaults["fallbackOnThinContent"] is True

    http_only = capabilities["web.scrape.http"]
    assert [candidate.ref for candidate in http_only.candidates] == ["nativeweb:scrape"]
    assert http_only.candidates[0].defaults["fallbackOnThinContent"] is False

    rendered = capabilities["web.scrape.rendered"]
    assert [candidate.ref for candidate in rendered.candidates] == ["firecrawl:scrape"]
