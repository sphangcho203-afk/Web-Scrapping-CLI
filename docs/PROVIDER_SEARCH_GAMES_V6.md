# Provider Search + Games v6

This expansion adds documented search/research and game-catalog providers to OpenCrawl's
existing Tool Mesh. The integration follows the same provider boundary used elsewhere:
credentials stay server-side, caller input is normalized into an allowlisted request shape,
and read-only provider attempts remain covered by OpenCrawl's retry, metering, settlement,
and reliability layers.

## New web provider

### You.com

Environment:

- `YDC_API_KEY`

Raw Tool Mesh refs:

- `you:search`
- `you:contents`
- `you:research`

Semantic routes:

- `web.search.semantic` includes You.com as an adaptive fallback.
- `web.context.agent` can request highlight-oriented grounding.
- `web.extract.urls` can use You.com Contents.
- `web.search.news` composes You.com, Tavily and Firecrawl.
- `web.research.synthesized` composes You.com Research and Firecrawl Agent.

The provider does not accept caller-supplied API keys, Authorization headers, OAuth scopes,
or arbitrary upstream request bodies.

## Firecrawl search expansion

The Firecrawl v2 search descriptor now exposes the documented source/category model:

- sources: `web`, `news`, `images`
- categories: `research`, `pdf`, `developer`
- enterprise controls: `anon` or `zdr` when enabled by the upstream account

OpenCrawl adds semantic routes for developer search, research-oriented search and image
search. Unknown top-level search fields are dropped before forwarding. Existing rejection
of sensitive target headers and browser actions remains in place.

## Game catalog providers

### RAWG

Environment:

- `RAWG_API_KEY`

Refs:

- `rawg:search-games`
- `rawg:game-detail`
- `rawg:platforms-search`
- `rawg:developers-search`
- `rawg:publishers-search`

### IGDB

Environment:

- `IGDB_CLIENT_ID`
- `IGDB_CLIENT_SECRET`, or an operator-provided `IGDB_ACCESS_TOKEN`

Refs:

- `igdb:search-games`
- `igdb:game-by-id`
- `igdb:search-platforms`

When OpenCrawl obtains an IGDB token itself, it uses Twitch's documented
`client_credentials` grant. OpenCrawl does not accept caller-controlled scopes or raw
Apicalypse bodies. Search text is normalized and interpolated only into fixed query
templates.

Semantic routes:

- `games.catalog.search`: IGDB -> RAWG
- `games.platform.search`: IGDB -> RAWG
- `games.developer.search`: RAWG

## Economics and reliability

You.com is treated as an operator-supplied metered provider. RAWG and IGDB are bounded
operator-key providers in the `free_tier` provider class. All calls flow through Tool Mesh,
so v5 provider failure classification, read-only retry policy, provider attempt telemetry,
shared reliability, circuit routing, and measured settlement apply without a separate
execution path.
