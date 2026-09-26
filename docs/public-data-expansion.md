# Public evidence and game data expansion

## Architecture and compatibility

The existing `fetcher.py` remains the only downloader for the new adapters. Its
optional per-hop URL guard adds crawl-origin and robots enforcement without
changing existing callers. Existing DNS/IP checks, redirect validation and body
limits still apply. `extractor.py` supplies main text and optional Trafilatura
extraction; `discovery.py` supplies published machine interfaces and feed links.
No authentication migration, credential storage, wallet balance, billing payment,
monitor persistence or existing API contract is replaced.

`PublicDataProvider` and `PublicGameProvider` register in the existing Tool Mesh
and semantic registry. `/api/public-data/{operation}` uses the same API-key
identity resolution, reservation and usage ledger as other dashboard tools.
The canonical `web/app.js` adds `/dashboard/data` and paginates the game catalog.
`web/cognitive-foundation.css` remains the live stylesheet.

## Callable operations

| Operation | Input | Output and bounds |
| --- | --- | --- |
| `publicdata:extract` / `web.public.extract` | `url` | HTML main text, tables, JSON-LD, JSON, CSV, RSS/Atom or sitemap; 1 MB source body |
| `publicdata:discover` / `web.public.discover` | `url` | Published links and advertised data interfaces; no guessed private endpoints |
| `publicdata:research` / `web.public.research` | `urls`, optional `query`, `max_pages` | 1–10 seed URLs, up to 20 page attempts, seed-origin links, source excerpts, hashes, timestamps and partial-failure diagnostics |
| `gamepublic:<appid>/news` | optional `count` 1–20 | Published news/update excerpts |
| `gamepublic:<appid>/activity` | none | Current connected players on the named platform |
| `gamepublic:<appid>/achievements` | none | Published global achievement percentages, where available |

Research is source-grounded retrieval, not a global search engine or generated
answer. Query terms rank excerpts. It respects robots disallows, crawl delays
and request rates. Redirects remain within the current seed origin and allowed
paths; adding another seed is required to collect a different origin. Dashboard
runs have a 25-second wall-clock bound and return partial evidence where possible.
No-source runs fail explicitly. MCP research is capped at 45 seconds.

The game manifest contains **132 titles** and **396 specific operations**.
Dota 2 extends its existing adapter. Existing game-specific profiles, match
histories and local match analysis remain available independently. Catalog
registration means an operation can be attempted, not that every upstream is
live or every game publishes every field. Empty data, HTTP failures and missing
statistics are distinct; none becomes invented player telemetry. Cache entries
retain original capture times and expire after 60 seconds (256-entry bound).

## Economics

New public-data/game executions reserve 2 base credits plus 3 per bounded source
request. Research reserves at most two requests per page attempt (document and
robots); final settlement counts actual attempted requests and returns unused
credits. A cached game read costs 2 credits; a fresh one costs 5. Semantic and
batch execution include their existing orchestration base. Failed requests can
consume measured work and disclose the charge. This is an explicit product
credit policy, not a claim that a public source charges this amount.

The older native web route now uses the same per-request rule. Batch fetch
reserves per URL; crawl reserves for its page limit and a possible crawl-policy
request per page origin. Settlement counts attempted document, robots and search
requests and releases the unused reservation. Crawl redirects stay on the page's
origin and obey its robots policy.

## Source and open-source review

Reviewed 2026-09-26:

- [ISteamNews](https://partner.steamgames.com/doc/webapi/ISteamNews): documented public news operation, bounded count/excerpt length.
- [ISteamUserStats](https://partner.steamgames.com/doc/webapi/ISteamUserStats): activity and global-achievement operations; individual player data uses separate authenticated operations.
- [Application records](https://store.steampowered.com/): each manifest ID produces a source catalog link; immutable IDs avoid title-dependent endpoint guessing.
- [Trafilatura](https://github.com/adbar/trafilatura): Apache-2.0 since 1.8; the repository already declares the 2.x optional extraction dependency and integrates it through `extractor.py`. Reused that integration.
- [Playwright Python](https://github.com/microsoft/playwright-python): existing optional browser/testing integration; Apache-2.0.
- [Scrapy](https://github.com/scrapy/scrapy): existing optional crawl backend; retained separately from short serverless requests.

No third-party repository code was copied or executed. These adapters are
original integration code around documented public operations and the existing
licensed extraction stack. No permissions, authentication scopes, private
endpoints or access controls are bypassed.

## Verification limits

Tests cover document formats, bounded inputs, XML entity rejection, crawl scope
and redirect guards, robots rules, timeout/partial results, billing, game schemas,
zero activity versus missing data, failures and cache isolation. Browser fixtures
cover catalog pagination/search and the public-data form across 320–1920px.
Live endpoint smoke checks were inaccessible from this execution environment;
132 catalog entries are not presented as 132 individually live-verified games.
A deployment smoke check of news, activity, achievements and public-source
research remains necessary before treating coverage as production-verified.
