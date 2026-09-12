# 🥷 Internet Hands — Web Scraping CLI

**Public internet intelligence, end to end.**

Internet Hands is the engine inside `Web-Scrapping-CLI`: a capability-driven toolkit for
fetching, rendering, extracting, indexing, monitoring, searching, discovering APIs, and
collecting structured intelligence from public or explicitly authorized internet sources.

> Fetch the evidence. Keep the provenance. Route to the best source.

## v0.3

v0.3 turns the project from a web collection engine into an extensible **internet intelligence
fabric**.

### Core web engine

- raw HTTP fetch with exact response-byte preservation
- redirect, status, header, timing, and SHA-256 provenance
- structured page extraction
- bounded same-origin crawling
- SQLite + FTS5 full-text search
- content-addressed raw object storage
- persistent watches and change events
- optional Playwright browser worker
- health and download inspection
- JSONL export
- FastAPI control plane

### Intelligence fabric

- capability catalog for official/public provider endpoints
- YouTube video and channel intelligence
- owner-authorized YouTube Analytics and revenue metrics
- clearly labeled public revenue scenarios using caller-supplied RPM assumptions
- GitHub public profile and repository collection
- Bluesky public profile/feed collection
- Hacker News item/user collection
- Mastodon public profile lookup
- Twitch user lookup with app credentials
- TikTok profile collection for the user who explicitly authorized the token
- exact-handle public username checks across selected providers
- public OpenAPI JSON/YAML discovery for GET/HEAD operations

The built-in endpoint catalog currently covers endpoint families across YouTube, GitHub,
Bluesky, Hacker News, Mastodon, Twitch, TikTok, Reddit, GitLab, Wikipedia, Wikidata,
OpenAlex, Crossref, npm, PyPI, and crates.io.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Optional browser worker:

```bash
pip install -e '.[browser]'
playwright install chromium
```

## Raw web collection

```bash
ih fetch https://example.com
ih links https://example.com
ih index https://example.com
ih search "example domain"
```

Index a bounded origin:

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

## Endpoint catalog

List known provider capabilities:

```bash
ih endpoints
ih endpoints --provider youtube
ih endpoints --capability profile --ready-only
```

The catalog is declarative. Each entry records:

- provider
- operation name
- capability
- HTTP method
- endpoint
- authentication mode
- required environment variables
- public/authorized classification
- local readiness

## Provider-backed intelligence

### YouTube

```bash
export YOUTUBE_API_KEY='...'

ih intel youtube-video 'https://www.youtube.com/watch?v=VIDEO_ID'
ih intel youtube-channel '@HANDLE'
```

Public video results include official metadata/statistics plus derived engagement signals.

For creator-owned analytics:

```bash
export YOUTUBE_ANALYTICS_ACCESS_TOKEN='...'

ih intel youtube-owner-analytics \
  --start 2026-09-01 \
  --end 2026-09-12
```

Monetary metrics require the YouTube account owner's authorized Analytics token.

For a public-video revenue scenario:

```bash
ih intel youtube-revenue-scenario 1000000 --rpm-low 1.5 --rpm-high 5.0
```

That command does **not** claim to know the creator's real revenue. It calculates a range from
the caller-supplied assumptions and labels the output accordingly.

### GitHub

```bash
ih intel github-user octocat
ih intel github-repos octocat
```

`GITHUB_TOKEN` is optional for public reads and can be configured for higher authenticated rate
limits.

### Bluesky

```bash
ih intel bluesky-profile example.bsky.social
ih intel bluesky-feed example.bsky.social --limit 25
```

### Hacker News

```bash
ih intel hn-item 8863
```

### Mastodon

```bash
ih intel mastodon-profile mastodon.social username
```

### Twitch

```bash
export TWITCH_CLIENT_ID='...'
export TWITCH_ACCESS_TOKEN='...'

ih intel twitch-user example
```

### TikTok

TikTok Display API data requires the user to authorize the application and required scopes.

```bash
export TIKTOK_ACCESS_TOKEN='...'
ih intel tiktok-me
```

### Public username checks

```bash
ih intel username somehandle
```

This checks the **exact public handle** on selected providers. Matching handles are not treated as
proof that accounts belong to the same person.

## OpenAPI discovery

Internet Hands can inspect a public OpenAPI/Swagger document and inventory its read-only
operations:

```bash
ih-openapi discover https://example.com/openapi.json
```

The result includes server information, operation IDs, paths, parameters, tags, inferred
capabilities, and source provenance. Discovery imports only GET/HEAD operations; authentication,
provider rules, and rate limits still apply before execution.

This is the mechanism for expanding beyond a fixed list of providers without creating hundreds
of brittle hard-coded scrapers.

## Environment

Copy `.env.example` or configure only the providers you use:

```text
INTERNET_HANDS_API_KEY
INTERNET_HANDS_DB
INTERNET_HANDS_ALLOW_UNAUTHENTICATED
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

The FastAPI control plane now fails closed by default.

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
CLI / FastAPI / agents
          │
          ▼
 target resolver + capability catalog
          │
    ┌─────┼──────────────┐
    ▼     ▼              ▼
official  OpenAPI      raw web
 API      discovery    / browser
    │       │              │
    └───────┴──────┬───────┘
                   ▼
        normalized intelligence
       + capture provenance/hash
                   │
          ┌────────┼────────┐
          ▼        ▼        ▼
        index    watches   analysis
          │        │        │
          └────────┴────┬───┘
                       ▼
                 apps / agents
```

Detailed design: [`docs/ENDPOINT_FABRIC.md`](docs/ENDPOINT_FABRIC.md)

Base storage architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## Video intelligence direction

v0.3 handles public metadata/statistics and owner-authorized analytics. The next media layer is
designed around evidence, not platform bypasses:

```text
metadata + authorized/caller-supplied transcript/media
                         │
                         ▼
                evidence + hashes
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
        transcript      frames       metrics
        analysis        analysis      analysis
            └────────────┼────────────┘
                         ▼
                   VideoIntel record
```

Planned analyzers include transcript segmentation, topics/entities, scene segmentation,
selected-frame OCR, visual-object signals, speech/language statistics, and engagement analysis.

## Data layout

```text
.internet-hands/
├── internet-hands.db
└── objects/
    └── ab/
        └── abcd...sha256
```

The database stores capture metadata, extracted documents, FTS records, watch jobs, and events.
Raw response bodies are kept in a SHA-256 content-addressed object store.

## Network and collection policy

Internet Hands is for public web data and sources the operator is authorized to access.

Defaults include:

- only HTTP/HTTPS targets
- localhost/private/link-local/multicast/reserved/unspecified target blocking
- redirect revalidation
- browser subrequest filtering
- bounded same-origin crawling
- optional robots.txt compliance
- response-size and timeout limits
- no credential theft, authentication bypass, CAPTCHA defeat, exploit delivery, or stealth/evasion

Production deployments should additionally enforce public-only egress at the network/container
layer to close DNS rebinding gaps.

## Roadmap

### v0.3 hardening

- [x] provider capability catalog
- [x] YouTube/GitHub/Bluesky/HN/Mastodon/Twitch/TikTok collector foundation
- [x] exact public username checks
- [x] OpenAPI GET/HEAD discovery
- [x] fail-closed FastAPI auth
- [ ] unified provider rate-limit state and circuit breakers
- [ ] provider error taxonomy and retry budgets
- [ ] network-level egress enforcement / DNS pinning
- [ ] mocked integration tests for every provider

### Intelligence expansion

- [ ] YouTube comments/upload history analysis
- [ ] Twitch video/stream collectors
- [ ] TikTok authorized video-list/query collectors
- [ ] Reddit OAuth adapters
- [ ] GitLab profile/project adapters
- [ ] Wikipedia/Wikidata research adapters
- [ ] OpenAlex/Crossref research adapters
- [ ] npm/PyPI/crates package intelligence
- [ ] RSS/Atom, sitemap, oEmbed, and JSON-LD adapters

### Media intelligence

- [ ] normalized `VideoIntel` schema
- [ ] transcript ingestion and segmentation
- [ ] frame-sampling interface
- [ ] pluggable vision/speech analyzers
- [ ] per-segment evidence and citations

### Agent scale

- [ ] Postgres backend
- [ ] queue-backed distributed workers
- [ ] capability router with health/cost/freshness scoring
- [ ] distributed caching
- [ ] streaming result events
- [ ] MCP/agent tool surface
- [ ] operator dashboard

## License

MIT
