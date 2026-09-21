# Internet Hands Capability Packs

Capability packs are the semantic layer above raw tools. They let an agent ask for a stable capability such as `web.fetch.page` or `mlbb.player.lookup` without memorizing a marketplace Actor name, RapidAPI host, OpenAPI operation id, or remote MCP tool name.

## Agent bootstrap

An agent only needs the Internet Hands MCP endpoint and its API key.

The preferred discovery flow is:

1. `mesh_route(intent)` — search semantic packs and external catalogs together.
2. `mesh_capability_resolve(id)` for a stable capability, or `mesh_describe_many(refs)` for raw shortlisted tools.
3. Validate the returned JSON Schema.
4. Use `mesh_capability_execute(...)` for read-only semantic fallbacks or `mesh_execute(...)` for an explicitly selected provider tool.
5. For asynchronous providers, continue with `mesh_job_status` and `mesh_results`.

This keeps the model context small. Thousands of provider schemas remain outside the prompt until the agent actually needs them.

## Built-in packs

### Web

- `web.search.google` → `apify:apify/google-search-scraper`
- `web.fetch.page` → `apify:apify/web-fetch`
- `web.research.rag` → `apify:apify/rag-web-browser`

These complement Internet Hands' native fetch/crawl/browser layers. The native layers remain available directly when the agent needs deterministic low-level control; the pack layer is for high-level routing.

### Social public-data research

- `social.instagram.scrape` → `apify:apify/instagram-scraper`
- `social.tiktok.scrape` → `apify:clockworks/tiktok-scraper`
- `social.x.scrape` → `apify:apidojo/tweet-scraper`

These capabilities are intended for public data and remain subject to Internet Hands provider policy and output bounds.

### Jobs

- `jobs.linkedin.search` → `apify:curious_coder/linkedin-jobs-scraper`

### Advertising research

- `ads.meta.library` → `apify:curious_coder/facebook-ads-library-scraper`

### Phone intelligence

- `phone.number.lookup` → `phoneintel:lookup`

This capability inspects telecom metadata such as validity, region, line type, carrier, time zones, MCC/MNC and configured risk signals. The local libphonenumber layer is always available. Optional external providers can enrich results. The capability intentionally excludes private subscriber/SIM-owner identity.

### Mobile Legends / MLBB

- `mlbb.player.lookup`
- `mlbb.nickname.lookup`
- `mlbb.hero.list`
- `mlbb.hero.detail`
- `mlbb.hero.analytics`
- `mlbb.academy.items`
- `mlbb.academy.spells`
- `mlbb.academy.emblems`
- `mlbb.rank.reference`

Player lookup prefers the configured RapidAPI source and can fall back to a smaller public nickname lookup when the required identifiers are available. Hero and reference capabilities are resolved dynamically from the configured MLBB OpenAPI catalog rather than freezing endpoint paths into model prompts.

## Raw provider planes

The semantic layer does not hide the underlying mesh. Agents may still discover tools directly through:

- `apify` — Actor marketplace, asynchronous runs, datasets
- `composio` — connected-app tool catalog and account-aware execution
- `rapidapi` — curated read-only RapidAPI manifests with server-side key injection
- `publicapi` — curated public read-only HTTP manifests
- `openapi` — dynamic GET/HEAD operations imported from configured public OpenAPI documents
- `mcp` — tools imported from configured public remote MCP servers

## Adding an API without changing Python

For a simple read-only HTTP API, add a JSON manifest through `INTERNET_HANDS_RAPIDAPI_TOOLS` or `INTERNET_HANDS_PUBLIC_API_TOOLS`.

For a full API catalog, add its public OpenAPI document through `INTERNET_HANDS_OPENAPI_SOURCES`.

For another MCP server, add its public Streamable-HTTP endpoint through `INTERNET_HANDS_REMOTE_MCP_SOURCES`.

For authenticated SaaS accounts, prefer the Composio provider so authentication and account selection stay outside model-visible arguments.

## Fallback rules

Automatic fallback is intentionally conservative:

- only semantic capabilities marked read-only may automatically move to another provider;
- a candidate whose descriptor is side-effecting is rejected from a read-only fallback;
- remote MCP tools default to potentially side-effecting unless the upstream server explicitly marks them read-only;
- credentials remain server-side;
- provider output is bounded before it reaches model context.

## Why packs instead of thousands of tools

A large agent should not load every marketplace schema into every prompt. Internet Hands keeps a compact meta-surface and performs discovery just in time. The stable interface is the capability id; the underlying provider can change, gain a fallback, or disappear without forcing the agent prompt to change.
