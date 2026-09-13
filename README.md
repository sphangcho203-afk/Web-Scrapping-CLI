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
- JSONL, WARC/1.1 and optional Parquet export
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

### Durable fleet

`ih-fleet` adds a persistent execution plane for crawls that should survive worker failure or run
across multiple worker processes/machines:

- SQLite WAL frontier for local multi-process workers
- Postgres frontier for multi-machine workers
- atomic leases and expired-lease recovery
- priorities, retry budgets and dead-letter state
- exponential backoff with jitter
- backend/host circuit breakers
- persistent cross-worker per-host pacing
- Postgres `FOR UPDATE SKIP LOCKED` leasing
- native, Crawlee, Crawl4AI and Scrapy worker backends
- bounded child discovery feeding the same Internet Hands index/provenance model

See [`docs/FLEET_ARCHITECTURE.md`](docs/FLEET_ARCHITECTURE.md).

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
| Native HTTP | exact-byte fetch + bounded hunt + fleet worker | active |
| Native Playwright | guarded JavaScript rendering | active optional |
| Microsoft Playwright MCP | persistent agent/browser interaction | MCP sidecar ready |
| Crawlee Python | HTTP fleet worker / queue-oriented crawling | execution adapter optional |
| Scrapy | high-throughput HTTP worker | execution adapter optional |
| Crawl4AI | browser/LLM-oriented rendered capture | execution adapter optional |
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

Distributed/analytics extras can be installed independently:

```bash
pip install -e '.[postgres]'
pip install -e '.[parquet]'
pip install -e '.[crawlee]'
pip install -e '.[crawl4ai]'
pip install -e '.[scrapy]'
```

Or stage all optional execution backends:

```bash
pip install -e '.[all-backends]'
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

## Fleet mode

Seed a durable local frontier:

```bash
ih-fleet seed https://example.com --scope origin
```

Run multiple worker processes against the same SQLite frontier:

```bash
ih-fleet drain --worker-id worker-1 --batch-size 16
# In another process/terminal:
ih-fleet drain --worker-id worker-2 --batch-size 16
```

Inspect queue state:

```bash
ih-fleet stats
```

For a multi-machine frontier, configure Postgres:

```bash
export INTERNET_HANDS_POSTGRES_DSN='postgresql://user:pass@host/dbname'
pip install -e '.[postgres]'

ih-fleet seed https://example.com --scope origin
ih-fleet drain --worker-id node-a --batch-size 32
```

Postgres fleet leasing uses row locks with `SKIP LOCKED`, so separate workers can claim distinct
jobs without a central scheduler.

The fleet can also normalize captures from optional external engines:

```bash
# Run only inside a worker environment whose network policy permits public internet egress
# while blocking private/loopback/link-local/metadata destinations.
ih-fleet drain --backend crawlee --allow-external-network
ih-fleet drain --backend crawl4ai --allow-external-network
ih-fleet drain --backend scrapy --allow-external-network
```

External networking is deliberately opt-in because third-party crawler/browser engines can perform
network activity outside Internet Hands' native HTTP transport. Application URL validation remains
in place, but production workers should additionally enforce public-only egress at the container or
VM/network layer.

The distributed frontier currently coordinates crawl jobs, retries, circuits and host pacing.
Capture/document storage remains the existing Internet Hands SQLite + object-store layer in this
branch.

## Portable datasets

Export archival WARC/1.1 records:

```bash
ih-export warc data/crawl.warc.gz
```

Export normalized documents/capture metadata to Parquet:

```bash
pip install -e '.[parquet]'
ih-export parquet data/documents.parquet
```

WARC records include target URL, capture timestamp, stored HTTP response headers/body and payload
SHA-256. Parquet uses Zstandard compression for analytics/ML workflows.

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

Configure only providers/infrastructure you use:

```text
INTERNET_HANDS_API_KEY
INTERNET_HANDS_DB
INTERNET_HANDS_ALLOW_UNAUTHENTICATED
INTERNET_HANDS_POSTGRES_DSN
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
        |
        +---- search --------+
        +---- OpenAPI -------+
        +---- providers -----+
        +---- raw web -------+
                            |
                            v
                    capability/router
          +-----------------+------------------+
          v                 v                  v
         HTTP             browser          adapters
          |                 |                  |
          +-----------------+------------------+
                            |
                 single hunt or durable fleet
                            |
              +-------------+-------------+
              v                           v
       SQLite frontier              Postgres frontier
              |                     (SKIP LOCKED)
              +-------------+-------------+
                            |
                   normalized capture
                            |
            extraction + discovery + provenance
                            |
              +-------------+-------------+
              v             v             v
            objects       SQLite/FTS     watches
                            |
                         exports
                     WARC / Parquet
                            |
                       apps / agents
```

Detailed designs:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/ENDPOINT_FABRIC.md`](docs/ENDPOINT_FABRIC.md)
- [`docs/BACKEND_FABRIC.md`](docs/BACKEND_FABRIC.md)
- [`docs/FLEET_ARCHITECTURE.md`](docs/FLEET_ARCHITECTURE.md)

## Data layout

```text
.internet-hands/
├── internet-hands.db
├── frontier.db
├── objects/
├── backends/
└── media/
```

The content database stores capture metadata, extracted documents, FTS records, watch jobs and
events. Raw response bodies are kept in a SHA-256 content-addressed object store. The local fleet
frontier stores leases/retries/circuits/host pacing separately in `frontier.db`; Postgres can replace
that frontier for distributed workers. Curated external source backends, when synced, live outside
the package source under `.internet-hands/backends/` and record their exact upstream commits.

## Network and collection policy

Internet Hands is for public web data and sources the operator is authorized to access.

Defaults and invariants include:

- HTTP/HTTPS public targets only
- localhost/private/link-local/multicast/reserved/unspecified target blocking
- public DNS resolution snapshot before native HTTP connections
- connected peer-IP validation when the transport exposes the server address
- redirect revalidation
- browser subrequest filtering for the native Playwright renderer
- bounded page/depth/domain/concurrency budgets
- `robots.txt` compliance by default in hunt/fleet flows
- cross-worker per-host pacing
- response-size and timeout limits
- retry budgets and host/backend circuit breakers
- no credential theft or authentication bypass
- no CAPTCHA defeat
- no exploit delivery
- no stealth/evasion or quota-evasion key rotation

External browser/crawler adapters require an explicit networking opt-in. Production deployments
should enforce public-only egress at the network/container layer because application URL checks
cannot provide perfect DNS/connection pinning for every third-party transport or browser stack.

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
- [x] durable SQLite frontier with leases/retries/dead-letter state
- [x] Postgres distributed frontier with `SKIP LOCKED`
- [x] queue-backed fleet workers
- [x] distributed host pacing + circuit breakers
- [x] Crawlee/Crawl4AI/Scrapy execution adapters
- [x] native DNS-resolution + connected-peer validation
- [x] WARC export
- [x] optional Parquet export
- [x] fail-closed FastAPI auth

### Next hardening

- [ ] shared Postgres capture/document store
- [ ] shared object storage (S3-compatible or equivalent)
- [ ] provider-specific rate-limit telemetry and circuit policy
- [ ] network-level public-only egress policy templates
- [ ] signed provenance manifests
- [ ] streaming result events
- [ ] worker metrics / operator dashboard

## License

MIT
