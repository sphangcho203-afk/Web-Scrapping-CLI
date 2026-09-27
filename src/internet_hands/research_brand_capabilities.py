from __future__ import annotations

from .capability_packs import Capability, CapabilityCandidate


def build_research_brand_capabilities() -> list[Capability]:
    return [
        Capability(
            id="web.search.semantic",
            name="Semantic multi-provider web search",
            description=(
                "Search the public web through documented agent-search APIs with provider "
                "fallbacks and normalized arguments."
            ),
            pack="web",
            tags=("web", "search", "semantic", "research", "exa", "tavily"),
            candidates=(
                CapabilityCandidate(
                    provider="exa",
                    ref="exa:search",
                    priority=5,
                    argument_map={"limit": "numResults"},
                    passthrough_arguments=True,
                ),
                CapabilityCandidate(
                    provider="tavily",
                    ref="tavily:search",
                    priority=10,
                    argument_map={"limit": "max_results"},
                    passthrough_arguments=True,
                ),
                CapabilityCandidate(
                    provider="firecrawl",
                    ref="firecrawl:search",
                    priority=20,
                    passthrough_arguments=True,
                ),
                CapabilityCandidate(
                    provider="nativeweb",
                    ref="nativeweb:search",
                    priority=40,
                    argument_map={"limit": "count"},
                    passthrough_arguments=True,
                ),
            ),
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    "includeDomains": {"type": "array", "items": {"type": "string"}},
                    "excludeDomains": {"type": "array", "items": {"type": "string"}},
                    "topic": {"type": "string"},
                    "freshness": {"type": "string"},
                    "country": {"type": "string"},
                },
            },
        ),
        Capability(
            id="web.extract.urls",
            name="Multi-provider public URL extraction",
            description=(
                "Extract clean public-web content from a bounded URL batch using documented "
                "Tavily or Exa content endpoints."
            ),
            pack="web",
            tags=("web", "extract", "contents", "tavily", "exa"),
            candidates=(
                CapabilityCandidate(
                    provider="tavily",
                    ref="tavily:extract",
                    priority=5,
                ),
                CapabilityCandidate(
                    provider="exa",
                    ref="exa:contents",
                    priority=10,
                ),
            ),
            input_schema={
                "type": "object",
                "required": ["urls"],
                "properties": {
                    "urls": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "items": {"type": "string"},
                    },
                    "query": {"type": "string"},
                    "text": {"type": "boolean"},
                    "highlights": {"type": "boolean"},
                    "summary": {"type": "boolean"},
                },
            },
        ),
        Capability(
            id="web.map.smart",
            name="Multi-provider site mapping",
            description=(
                "Map public website URLs with documented graph-based providers before falling "
                "back to first-party link discovery."
            ),
            pack="web",
            tags=("web", "map", "site", "discovery", "tavily", "firecrawl"),
            candidates=(
                CapabilityCandidate(
                    provider="tavily",
                    ref="tavily:map",
                    priority=5,
                ),
                CapabilityCandidate(
                    provider="firecrawl",
                    ref="firecrawl:map",
                    priority=10,
                ),
                CapabilityCandidate(
                    provider="nativeweb",
                    ref="nativeweb:map",
                    priority=30,
                ),
            ),
        ),
        Capability(
            id="web.crawl.smart",
            name="Multi-provider bounded site crawl",
            description=(
                "Traverse a public website through documented graph crawlers with bounded "
                "limits and first-party fallback."
            ),
            pack="web",
            tags=("web", "crawl", "site", "graph", "tavily", "firecrawl"),
            candidates=(
                CapabilityCandidate(
                    provider="tavily",
                    ref="tavily:crawl",
                    priority=5,
                ),
                CapabilityCandidate(
                    provider="firecrawl",
                    ref="firecrawl:crawl",
                    priority=10,
                ),
                CapabilityCandidate(
                    provider="nativeweb",
                    ref="nativeweb:crawl",
                    priority=30,
                ),
            ),
        ),
    ]
