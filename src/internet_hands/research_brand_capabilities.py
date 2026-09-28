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
            tags=("web", "search", "semantic", "research", "exa", "you", "tavily"),
            candidates=(
                CapabilityCandidate(
                    provider="exa",
                    ref="exa:search",
                    priority=5,
                    argument_map={"limit": "numResults"},
                    passthrough_arguments=True,
                ),
                CapabilityCandidate(
                    provider="you",
                    ref="you:search",
                    priority=7,
                    argument_map={
                        "limit": "count",
                        "includeDomains": "include_domains",
                        "excludeDomains": "exclude_domains",
                    },
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
            id="web.context.agent",
            name="Agent-ready web grounding context",
            description=(
                "Retrieve extracted public-web grounding context for an agent or RAG pipeline, "
                "preferring Brave LLM Context and falling back to semantic research providers."
            ),
            pack="web",
            tags=("web", "context", "rag", "agent", "brave", "you", "exa", "tavily"),
            candidates=(
                CapabilityCandidate(
                    provider="nativeweb",
                    ref="nativeweb:context",
                    priority=5,
                    argument_map={"limit": "count"},
                    passthrough_arguments=True,
                ),
                CapabilityCandidate(
                    provider="you",
                    ref="you:search",
                    priority=8,
                    argument_map={"limit": "count"},
                    defaults={"extraction_mode": "highlights"},
                    passthrough_arguments=True,
                ),
                CapabilityCandidate(
                    provider="exa",
                    ref="exa:search",
                    priority=10,
                    argument_map={"limit": "numResults"},
                    defaults={"text": True, "highlights": True},
                    passthrough_arguments=True,
                ),
                CapabilityCandidate(
                    provider="tavily",
                    ref="tavily:search",
                    priority=15,
                    argument_map={"limit": "max_results"},
                    defaults={
                        "search_depth": "advanced",
                        "include_raw_content": True,
                    },
                    passthrough_arguments=True,
                ),
            ),
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    "country": {"type": "string"},
                    "freshness": {"type": "string"},
                    "maximum_number_of_tokens": {
                        "type": "integer",
                        "minimum": 1024,
                        "maximum": 32768,
                    },
                },
            },
        ),
        Capability(
            id="web.extract.urls",
            name="Multi-provider public URL extraction",
            description=(
                "Extract clean public-web content from a bounded URL batch using documented "
                "Tavily, You.com, or Exa content endpoints."
            ),
            pack="web",
            tags=("web", "extract", "contents", "tavily", "you", "exa"),
            candidates=(
                CapabilityCandidate(
                    provider="tavily",
                    ref="tavily:extract",
                    priority=5,
                ),
                CapabilityCandidate(
                    provider="you",
                    ref="you:contents",
                    priority=8,
                    defaults={"formats": ["markdown", "metadata"]},
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
            id="web.search.news",
            name="Multi-provider live news search",
            description=(
                "Search current public news through documented providers with normalized "
                "freshness, domain, and result-count controls."
            ),
            pack="web",
            tags=("web", "search", "news", "you", "tavily", "firecrawl"),
            candidates=(
                CapabilityCandidate(
                    provider="you",
                    ref="you:search",
                    priority=5,
                    argument_map={
                        "limit": "count",
                        "includeDomains": "include_domains",
                        "excludeDomains": "exclude_domains",
                    },
                    defaults={"result_section": "news"},
                    passthrough_arguments=True,
                ),
                CapabilityCandidate(
                    provider="tavily",
                    ref="tavily:search",
                    priority=10,
                    argument_map={"limit": "max_results"},
                    defaults={"topic": "news"},
                    passthrough_arguments=True,
                ),
                CapabilityCandidate(
                    provider="firecrawl",
                    ref="firecrawl:search",
                    priority=15,
                    defaults={"sources": ["news"]},
                    passthrough_arguments=True,
                ),
            ),
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    "freshness": {"type": "string"},
                    "country": {"type": "string"},
                    "includeDomains": {"type": "array", "items": {"type": "string"}},
                    "excludeDomains": {"type": "array", "items": {"type": "string"}},
                },
            },
        ),
        Capability(
            id="web.research.synthesized",
            name="Cited multi-step web research",
            description=(
                "Run a documented, citation-oriented research workflow with a bounded "
                "synchronous You.com route and Firecrawl Agent fallback."
            ),
            pack="web",
            tags=("web", "research", "citations", "you", "firecrawl"),
            candidates=(
                CapabilityCandidate(
                    provider="you",
                    ref="you:research",
                    priority=5,
                    argument_map={"query": "input"},
                    passthrough_arguments=True,
                ),
                CapabilityCandidate(
                    provider="firecrawl",
                    ref="firecrawl:agent",
                    priority=20,
                    argument_map={"query": "prompt"},
                    passthrough_arguments=True,
                ),
            ),
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "research_effort": {
                        "type": "string",
                        "enum": ["lite", "standard", "deep", "exhaustive"],
                    },
                    "include_domains": {"type": "array", "items": {"type": "string"}},
                    "exclude_domains": {"type": "array", "items": {"type": "string"}},
                    "freshness": {"type": "string"},
                    "country": {"type": "string"},
                },
            },
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
