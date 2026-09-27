from __future__ import annotations

from .capability_packs import Capability, CapabilityCandidate


def build_intelligence_capabilities() -> list[Capability]:
    return [
        Capability(
            id="web.fetch.resilient",
            name="Resilient public web extraction",
            description=(
                "Collect and extract a public page with deterministic HTTP first, then guarded "
                "rendered/open-source backends when the page genuinely requires them."
            ),
            pack="web-intelligence",
            tags=("web", "scrape", "extract", "playwright", "fallback", "provenance"),
            candidates=(
                CapabilityCandidate(
                    provider="intelligence",
                    ref="intelligence:smart-fetch",
                    priority=10,
                    passthrough_arguments=True,
                ),
            ),
            input_schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string"},
                    "render": {"enum": ["auto", "never", "always"]},
                    "backend": {
                        "enum": [
                            "auto",
                            "native-http",
                            "native-playwright",
                            "crawlee-http",
                            "crawl4ai",
                            "scrapy",
                        ]
                    },
                    "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 60},
                    "minimum_text": {"type": "integer", "minimum": 1, "maximum": 20000},
                },
            },
        ),
        Capability(
            id="web.interfaces.discover",
            name="Discover published machine interfaces",
            description=(
                "Discover public feeds, sitemaps, JSON-LD and bounded OpenAPI candidates "
                "without guessing private endpoints."
            ),
            pack="web-intelligence",
            tags=("web", "api", "openapi", "feed", "sitemap", "discovery"),
            candidates=(
                CapabilityCandidate(
                    provider="intelligence",
                    ref="intelligence:discover-interfaces",
                    priority=10,
                    passthrough_arguments=True,
                ),
            ),
            input_schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string"},
                    "probe_openapi": {"type": "boolean"},
                },
            },
        ),
        Capability(
            id="web.search.extract",
            name="Search and extract public evidence",
            description=(
                "Run bounded web search and collect the top result pages with extraction, "
                "provenance and rendered fallback where needed."
            ),
            pack="web-intelligence",
            tags=("web", "search", "research", "extract", "evidence"),
            candidates=(
                CapabilityCandidate(
                    provider="intelligence",
                    ref="intelligence:search-extract",
                    priority=10,
                    passthrough_arguments=True,
                ),
            ),
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "count": {"type": "integer", "minimum": 1, "maximum": 5},
                    "render": {"enum": ["auto", "never", "always"]},
                },
            },
        ),
    ]
