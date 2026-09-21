from __future__ import annotations

from internet_hands.firecrawl_capabilities import build_firecrawl_capabilities


def test_core_web_capabilities_have_independent_native_fallbacks() -> None:
    capabilities = {item.id: item for item in build_firecrawl_capabilities()}
    expected = {
        "web.fetch.page": "nativeweb:fetch",
        "web.search.live": "nativeweb:search",
        "web.map.site": "nativeweb:map",
        "web.crawl.site": "nativeweb:crawl",
        "web.scrape.batch": "nativeweb:batch-fetch",
    }
    for capability_id, ref in expected.items():
        candidates = capabilities[capability_id].candidates
        assert any(item.ref == ref for item in candidates)


def test_native_fallback_is_never_first_when_specialist_provider_exists() -> None:
    capabilities = {item.id: item for item in build_firecrawl_capabilities()}
    for capability_id in (
        "web.fetch.page",
        "web.search.live",
        "web.map.site",
        "web.crawl.site",
        "web.scrape.batch",
    ):
        candidates = sorted(capabilities[capability_id].candidates, key=lambda item: item.priority)
        assert candidates[0].provider == "firecrawl"
        assert candidates[-1].provider == "nativeweb"
