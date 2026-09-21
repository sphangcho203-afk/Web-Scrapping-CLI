from __future__ import annotations

from .capability_packs import Capability, CapabilityCandidate


def build_firecrawl_capabilities() -> list[Capability]:
    """Web capability pack that composes Firecrawl with existing fallback providers."""
    return [
        Capability(
            id="web.fetch.page",
            name="Resilient public page fetch",
            description=(
                "Fetch a public page as clean LLM-ready content, preferring Firecrawl and "
                "falling back to Apify web-fetch."
            ),
            pack="web",
            tags=("web", "fetch", "scrape", "markdown", "firecrawl", "apify"),
            candidates=(
                CapabilityCandidate(
                    provider="firecrawl",
                    ref="firecrawl:scrape",
                    priority=5,
                    note="Primary JS-capable page extraction via Firecrawl v2.",
                ),
                CapabilityCandidate(
                    provider="apify",
                    ref="apify:apify/web-fetch",
                    priority=20,
                    note="Apify fallback for resilient public-page fetching.",
                ),
                CapabilityCandidate(
                    provider="nativeweb",
                    ref="nativeweb:fetch",
                    priority=40,
                    note="First-party bounded HTTP fallback with SSRF-safe redirects.",
                ),
            ),
        ),
        Capability(
            id="web.search.live",
            name="Live web search with optional page content",
            description=(
                "Search the live web and optionally return scraped content for the results."
            ),
            pack="web",
            tags=("web", "search", "research", "firecrawl"),
            candidates=(
                CapabilityCandidate(
                    provider="firecrawl",
                    ref="firecrawl:search",
                    priority=5,
                ),
                CapabilityCandidate(
                    provider="nativeweb",
                    ref="nativeweb:search",
                    priority=30,
                    note="Brave-backed first-party search fallback when configured.",
                ),
            ),
        ),
        Capability(
            id="web.research.rag",
            name="Web research for an agent",
            description=(
                "Gather public-web evidence for a research goal, preferring Firecrawl Agent "
                "and falling back to Apify RAG web browsing."
            ),
            pack="web",
            tags=("web", "research", "rag", "agent", "firecrawl", "apify"),
            candidates=(
                CapabilityCandidate(
                    provider="firecrawl",
                    ref="firecrawl:agent",
                    priority=5,
                    argument_map={"query": "prompt"},
                ),
                CapabilityCandidate(
                    provider="apify",
                    ref="apify:apify/rag-web-browser",
                    priority=20,
                ),
            ),
        ),
        Capability(
            id="web.map.site",
            name="Site URL map",
            description="Discover a public site's relevant URLs without a full content crawl.",
            pack="web",
            tags=("web", "site", "map", "links", "discovery", "firecrawl"),
            candidates=(
                CapabilityCandidate(
                    provider="firecrawl",
                    ref="firecrawl:map",
                    priority=5,
                ),
                CapabilityCandidate(
                    provider="nativeweb",
                    ref="nativeweb:map",
                    priority=30,
                    note="First-party bounded link-discovery fallback.",
                ),
            ),
        ),
        Capability(
            id="web.crawl.site",
            name="Public site crawl",
            description="Crawl a public website into a bounded LLM-ready document corpus.",
            pack="web",
            tags=("web", "site", "crawl", "corpus", "firecrawl"),
            candidates=(
                CapabilityCandidate(
                    provider="firecrawl",
                    ref="firecrawl:crawl",
                    priority=5,
                ),
                CapabilityCandidate(
                    provider="nativeweb",
                    ref="nativeweb:crawl",
                    priority=30,
                    note="First-party bounded robots-aware crawler fallback.",
                ),
            ),
        ),
        Capability(
            id="web.scrape.batch",
            name="Batch public page scrape",
            description="Scrape multiple public URLs as one asynchronous Firecrawl job.",
            pack="web",
            tags=("web", "scrape", "batch", "firecrawl"),
            candidates=(
                CapabilityCandidate(
                    provider="firecrawl",
                    ref="firecrawl:batch-scrape",
                    priority=5,
                ),
                CapabilityCandidate(
                    provider="nativeweb",
                    ref="nativeweb:batch-fetch",
                    priority=30,
                    note="First-party bounded concurrent fetch fallback.",
                ),
            ),
        ),
        Capability(
            id="web.extract.structured",
            name="Structured website extraction",
            description=(
                "Extract schema-shaped data from one or more public URLs; Firecrawl Agent is "
                "preferred for new autonomous research, while the extract endpoint remains available."
            ),
            pack="web",
            tags=("web", "extract", "json", "structured-data", "firecrawl"),
            candidates=(
                CapabilityCandidate(
                    provider="firecrawl",
                    ref="firecrawl:agent",
                    priority=5,
                ),
                CapabilityCandidate(
                    provider="firecrawl",
                    ref="firecrawl:extract",
                    priority=20,
                ),
            ),
        ),
    ]
