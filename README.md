# 🥷 Internet Hands — Web Scraping CLI

**Public internet intelligence, end to end.**

Internet Hands is the engine inside `Web-Scrapping-CLI`: a capability-driven toolkit for
searching, fetching, rendering, extracting, crawling, indexing, monitoring, discovering APIs,
analyzing caller-supplied media, and collecting structured intelligence from public or explicitly
authorized internet sources.

> Find the source. Fetch the evidence. Keep the provenance. Route to the right engine.

## v0.3 — internet intelligence fabric

v0.3 turns the project from a single web collector into a layered internet-access subsystem for
apps and agents.

### Core collection

- exact-byte HTTP capture with status, redirects, headers, timing, SHA-256 and source URL
- content-addressed raw object store
- structured HTML/text extraction
- optional Trafilatura 2.x main-text/metadata enhancement
- SQLite + FTS5 full-text index
- persistent watches and change events
- optional guarded Playwright renderer
- health checks and download inspection
- JSONL export
- authenticated FastAPI control plane

### Search, hunt and discovery

- Brave Search-backed web/news/image/video discovery with strict SafeSearch
- search-seeded and URL-seeded bounded hunt frontier
- URL canonicalization and tracker removal
- URL + content-hash deduplication
- page/depth/domain/concurrency budgets
- per-host pacing and `robots.txt` checks by default
- optional Playwright fallback for thin JS-heavy pages
- RSS, Atom, JSON Feed, sitemap and published machine-interface frontier expansion
- HTML discovery for oEmbed, manifests, JSON-LD and OpenAPI/Swagger references
- public OpenAPI/Swagger JSON/YAML inventory for GET/HEAD operations

### Provider intelligence

Built-in collectors and endpoint descriptions span:

- YouTube — search, videos, channels, comments, upload history, public statistics, owner analytics
- GitHub — public users and repositories
- Bluesky — profiles, author feeds and post search
- Hacker News — items and users
- Mastodon — public profiles and statuses
- Twitch — users, videos and live-stream metadata
- TikTok — authorized profile and authorized video list
- GitLab — public users
- Wikipedia + Wikidata
- OpenAlex + Crossref
- npm + PyPI + crates.io
- Reddit endpoint foundation
- Brave Search web/news/images/videos

YouTube creator revenue uses owner-authorized YouTube Analytics. Public-video revenue commands are
explicitly labeled RPM scenarios rather than claims about a creator's real earnings.

### Media evidence

`ih-media` works with media the caller already possesses or is authorized to process:

- file SHA-256 provenance
- ffprobe media metadata
- deterministic ffmpeg frame sampling
- frame hashes
- SRT/WebVTT/plain transcript cleanup
- transcript timing and words-per-minute metrics
- top terms, hashtags, mentions and URLs
- reproducible media-bundle manifests

This creates evidence suitable for downstream vision/speech/LLM analysis without requiring a
platform-access bypass.

### Backend fabric

Internet Hands remains the policy/provenance/index control plane and can stage or route to
specialized open-source engines:

| Engine | Main role | State |
| --- | --- | --- |
| Native HTTP | exact-byte fetch + bounded hunt | active |
| Native Playwright | guarded JavaScript rendering | active optional |
| Microsoft Playwright MCP | persistent agent/browser interaction | MCP sidecar ready |
| Crawlee Python | scalable request queues/retries/browser crawling | curated backend |
| Scrapy | high-throughput HTTP crawling | curated backend |
| Crawl4AI | LLM-oriented browser extraction | curated backend |
| Trafilatura | main-text + metadata extraction | active optional |
| Firecrawl | self-hosted web-data service | external-service only by default |

See [`docs/BACKEND_FABRIC.md`](docs/BACKEND_FABRIC.md) for routing, licensing and the current
Playwright MCP capability surface.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Optional browser support:

```bash
pip install -e '.[browser]'
playwright install chromium
```

Optional current Trafilatura extraction backend:

```bash
pip install -e '.[extraction]'
```

## Raw collection and local search

```bash
ih fetch https://example.com
ih links https://example.com
ih index https://example.com
ih search "example domain"
```

Same-origin crawl-to-index:

```bash
ih index-crawl https://example.com --max-pages 50 --respect-robots
```

Persistent watches:

```bash
ih watch add https://example.com --every 3600
ih watch list
ih watch run
```

Export the local knowledge base:

```bash
ih export data/export.jsonl
```

## Internet hunt

Start from an explicit URL:

```bash
ih-hunt run \
  --seed https://example.com \
  --scope origin \
  --max-pages 200 \
  --max-depth 4
```

Start from search results and allow a bounded multi-domain frontier:

```bash
export BRAVE_SEARCH_API_KEY='...'

ih-hunt run \
  --query "open source retrieval systems" \
  --scope web \
  --search-count 10 \
  --max-domains 20 \
  --max-pages 300 \
  --max-depth 3
```

Add guarded browser rendering when raw HTTP produces a thin JS shell:

```bash
ih-hunt run \
  --seed https://example.com \
  --browser-fallback \
  --browser-text-threshold 200
```

The browser fallback is heuristic and bounded. The HTTP capture remains the first path; Playwright
is used only when enabled and the page looks dynamic with insufficient extracted text.

## Broad search

```bash
export BRAVE_SEARCH_API_KEY='...'

ih-search web "distributed crawlers"
ih-search news "web standards"
ih-search images "robotics laboratory"
ih-search videos "database internals"
```

Search uses strict SafeSearch in the built-in Brave provider.

## Published-interface discovery

Inspect a normal public page for feeds, JSON-LD, oEmbed, manifests, sitemap declarations and
published API descriptions:

```bash
ih-discover inspect https://example.com
```

Optionally check a small fixed set of conventional OpenAPI publication paths:

```bash
ih-discover inspect https://example.com --probe-openapi
```

This is bounded metadata discovery, not arbitrary hidden-path enumeration.

## OpenAPI discovery

```bash
ih-openapi discover https://example.com/openapi.json
```

The result inventories read-only GET/HEAD operations with server information, paths, parameters,
tags, operation IDs, inferred capabilities and source SHA-256 provenance. Provider authentication
and rate limits still apply before any operation is used.

## Backend manager

```bash
# See curated repositories, roles and license posture.
ih-backends list

# Shallow-clone/update the default curated source backends.
# Exact upstream commits are recorded locally.
ih-backends sync all

# Distinguish cloned source from actually runnable dependencies.
ih-backends status

# Ask which backend should handle a workload.
ih-backends plan static
ih-backends plan dynamic
ih-backends plan interactive
ih-backends plan throughput
ih-backends plan article
ih-backends plan llm-extraction

# Emit portable Microsoft Playwright MCP configuration.
ih-backends playwright-mcp-config
```

The default sync allowlist contains Microsoft Playwright MCP, Crawlee Python, Scrapy, Crawl4AI and
Trafilatura. Firecrawl remains external-service only by default because its core has different
licensing obligations from this MIT project.

## Provider-backed intelligence

List the built-in endpoint catalog:

```bash
ih endpoints
ih endpoints --provider youtube
ih endpoints --capability search --ready-only
```

Examples:

```bash
export YOUTUBE_API_KEY='...'
ih intel youtube-video 'https://www.youtube.com/watch?v=VIDEO_ID'
ih intel youtube-channel '@HANDLE'

ih-social youtube-search "database internals"
ih-social youtube-comments VIDEO_ID --limit 100

ih intel github-user octocat
ih intel github-repos octocat

ih-social bluesky-search "open source"

ih-data wikipedia-search "Ada Lovelace"
ih-data openalex-search "retrieval augmented generation"
ih-data pypi-package httpx
```

Creator-owned YouTube analytics:

```bash
export YOUTUBE_ANALYTICS_ACCESS_TOKEN='...'

ih intel youtube-owner-analytics \
  --start 2026-09-01 \
  --end 2026-09-12
```

Public-video scenario only:

```bash
ih intel youtube-revenue-scenario 1000000 --rpm-low 1.5 --rpm-high 5.0
```

Exact public handle checks:

```bash
ih intel username somehandle
```

Matching usernames are evidence of matching strings, not proof that accounts belong to the same
person.

## Media analysis

```bash
ih-media probe ./video.mp4
ih-media frames ./video.mp4 --count 12 --output .internet-hands/media/frames
ih-media transcript ./captions.vtt
ih-media bundle ./video.mp4 --transcript ./captions.vtt
```

Media commands operate on caller-supplied/authorized files. They do not fetch protected platform
media or defeat access controls.

## Environment

Configure only providers you use:

```text
INTERNET_HANDS_API_KEY
INTERNET_HANDS_DB
INTERNET_HANDS_ALLOW_UNAUTHENTICATED
BRAVE_SEARCH_API_KEY
YOUTUBE_API_KEY
YOUTUBE_ANALYTICS_ACCESS_TOKEN
GITHUB_TOKEN
TWITCH_CLIENT_ID
TWITCH_ACCESS_TOKEN
TIKTOK_ACCESS_TOKEN
REDDIT_ACCESS_TOKEN
```

Provider credentials are read from environment variables and are not written into provenance
records.

## Local API

The FastAPI control plane fails closed by default:

```bash
export INTERNET_HANDS_API_KEY='change-me'
export INTERNET_HANDS_DB='.internet-hands/internet-hands.db'
ih serve --host 127.0.0.1 --port 8787
```

Example:

```bash
curl -H 'X-API-Key: change-me' \
  'http://127.0.0.1:8787/v1/search?q=example'
```

For intentionally unauthenticated trusted local development only:

```bash
export INTERNET_HANDS_ALLOW_UNAUTHENTICATED=1
```

Do not expose an unrestricted arbitrary-URL fetch API anonymously to the public internet.

## Architecture

```text
queries / URLs / agents
        │
        ├──── search ─────┐
        ├──── OpenAPI ────┤
        ├──── providers ──┤
        └──── raw web ────┘
                         │
                         ▼
                 capability/router
              ┌──────────┼──────────┐
              ▼          ▼          ▼
             HTTP      browser    adapters
              │          │          │
              └──────────┼──────────┘
                         ▼
          capture + extraction + provenance
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
           objects    SQLite/FTS   watches
              │          │          │
              └──────────┼──────────┘
                         ▼
                    apps / agents
```

Detailed designs:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/ENDPOINT_FABRIC.md`](docs/ENDPOINT_FABRIC.md)
- [`docs/BACKEND_FABRIC.md`](docs/BACKEND_FABRIC.md)

## Data layout

```text
.internet-hands/
├── internet-hands.db
├── objects/
├── backends/
└── media/
```

The database stores capture metadata, extracted documents, FTS records, watch jobs and events.
Raw response bodies are kept in a SHA-256 content-addressed object store. Curated external source
backends, when synced, live outside the package source under `.internet-hands/backends/` and record
their exact upstream commits.

## Network and collection policy

Internet Hands is for public web data and sources the operator is authorized to access.

Defaults and invariants include:

- HTTP/HTTPS public targets only
- localhost/private/link-local/multicast/reserved/unspecified target blocking
- redirect revalidation
- browser subrequest filtering
- bounded page/depth/domain/concurrency budgets
- `robots.txt` compliance by default in hunt/crawl flows
- per-host pacing
- response-size and timeout limits
- no credential theft or authentication bypass
- no CAPTCHA defeat
- no exploit delivery
- no stealth/evasion or quota-evasion key rotation

Production deployments should additionally enforce public-only egress at the network/container
layer to close DNS rebinding/TOCTOU gaps.

## Roadmap

### Completed in v0.3 branch

- [x] provider capability catalog
- [x] broad web/news/image/video search provider
- [x] YouTube/GitHub/Bluesky/HN/Mastodon/Twitch/TikTok collectors
- [x] YouTube comments and upload-history collectors
- [x] exact public username checks
- [x] Wikipedia/Wikidata/OpenAlex/Crossref/GitLab/package collectors
- [x] OpenAPI GET/HEAD discovery
- [x] RSS/Atom/JSON Feed/sitemap/oEmbed/JSON-LD discovery
- [x] search-seeded bounded multi-domain hunt frontier
- [x] optional guarded Playwright hunt fallback
- [x] caller-supplied media metadata/frame/transcript evidence pipeline
- [x] curated backend clone/status manager
- [x] backend intent router
- [x] optional Trafilatura extraction backend
- [x] fail-closed FastAPI auth

### Next hardening

- [ ] unified provider rate-limit state + circuit breakers
- [ ] provider error taxonomy and retry budgets
- [ ] network-level public-only egress enforcement / connection pinning
- [ ] Postgres backend
- [ ] queue-backed distributed workers
- [ ] Crawlee/Scrapy/Crawl4AI worker protocol implementations
- [ ] WARC + Parquet import/export
- [ ] signed provenance manifests
- [ ] streaming result events
- [ ] operator dashboard

## License

MIT
