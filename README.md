# 🥷 Internet Hands — Web Scrapping CLI

**Public-web intelligence, end to end.**

**Internet Hands** is the engine inside **Web-Scrapping-CLI**: an open-source toolkit for fetching, rendering, extracting, indexing, monitoring, searching, and exporting public web data while preserving provenance back to the source capture.

> Fetch the bytes. Keep the evidence. Build knowledge from it.

## v0.2 capabilities

- **Raw fetch** — status, headers, body, redirects, timing, SHA-256, and exact response bytes.
- **Structured extraction** — title, description, headings, readable text, and normalized links.
- **Persistent index** — SQLite metadata plus FTS5 full-text search.
- **Content-addressed object store** — raw response bodies are deduplicated by SHA-256.
- **Crawl-to-index pipeline** — bounded same-origin collection directly into search.
- **Persistent web watches** — scheduled jobs, hash change detection, and event history.
- **API inspection** — JSON/text APIs with the source response envelope preserved.
- **Browser rendering** — optional isolated Playwright worker for JavaScript-rendered public pages.
- **Health checks** — availability, latency, status, and content type.
- **Download preparation** — inspect filename, size, type, disposition, and final URL.
- **Exports** — newline-delimited JSON for downstream analysis and pipelines.
- **Adapter SDK foundation** — common extension point for HTTP, JSON APIs, and future platform adapters.
- **FastAPI control plane** — expose collection, indexing, search, watches, and rendering to apps/agents.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

ih fetch https://example.com
ih index https://example.com
ih search "example domain"
```

Index an entire bounded origin:

```bash
ih index-crawl https://example.com --max-pages 50 --respect-robots
```

Create a persistent watch and run jobs that are due:

```bash
ih watch add https://example.com --every 3600
ih watch list
ih watch run
```

Export the local knowledge base:

```bash
ih export data/export.jsonl
```

### Optional browser worker

```bash
pip install -e '.[browser]'
playwright install chromium
ih browser https://example.com
```

The browser worker validates the top-level target and intercepts subresource requests so private, loopback, link-local, and other non-public addresses are blocked by the same policy layer.

## Local API

```bash
export INTERNET_HANDS_API_KEY='change-me'
export INTERNET_HANDS_DB='.internet-hands/internet-hands.db'
ih serve --host 127.0.0.1 --port 8787
```

Examples:

```bash
curl -H "X-API-Key: change-me" \
  'http://127.0.0.1:8787/v1/search?q=example'

curl -X POST -H "X-API-Key: change-me" \
  'http://127.0.0.1:8787/v1/index?url=https%3A%2F%2Fexample.com'
```

## Architecture

```text
CLI / FastAPI / agents
          │
          ▼
   public-target policy
          │
     ┌────┴─────┐
     ▼          ▼
 HTTP worker  Browser worker (optional)
     │          │
     └────┬─────┘
          ▼
 raw capture + SHA-256 provenance
          │
     ┌────┼─────────────┐
     ▼    ▼             ▼
 extract index       monitor
     │    │             │
     └────┴──────┬──────┘
                 ▼
        SQLite + FTS5 + objects
                 │
          search / export / API
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for design details.

## Data layout

By default:

```text
.internet-hands/
├── internet-hands.db
└── objects/
    └── ab/
        └── abcd...sha256
```

The database stores metadata, extracted documents, FTS records, watch jobs, and watch events. Raw response bodies live in a content-addressed object store and are referenced from capture records.

## Safety and deployment model

Internet Hands is meant for public web data and sources you are authorized to access. It is deliberately close to the network layer, so the defaults matter:

- localhost, private, link-local, multicast, reserved, and unspecified targets are blocked;
- only `http` and `https` are supported;
- redirect destinations are revalidated;
- browser subrequests are filtered by the same target policy;
- crawl scope is bounded and same-origin;
- `robots.txt` can be honored for crawl/index operations;
- response size and timeout limits are enforced;
- it does not provide credential theft, authentication bypass, CAPTCHA defeat, exploit delivery, or stealth/evasion features.

For an internet-facing deployment, add authenticated users, quotas, network-level egress controls, isolated browser containers, and observability. Do not expose an unrestricted arbitrary-URL fetch API anonymously.

## Roadmap

- [x] Raw fetch + exact-byte provenance
- [x] Link extraction and document extraction
- [x] API inspection
- [x] Same-origin crawler
- [x] Crawl-to-index pipeline
- [x] SQLite + FTS5 knowledge index
- [x] Persistent scheduled watches + event store
- [x] Health and download inspection
- [x] Optional Playwright browser worker
- [x] Adapter SDK foundation
- [x] JSONL export
- [x] FastAPI service
- [ ] Diff engine: text, headers, DOM, and visual changes
- [ ] WARC export and import
- [ ] Parquet export
- [ ] Postgres backend
- [ ] Queue-backed distributed workers
- [ ] Web dashboard with search, capture graph, and watch timeline
- [ ] Signed provenance manifests
- [ ] Production adapter packages for official/public platform APIs

## Repository

GitHub: `sphangcho203-afk/Web-Scrapping-CLI`

## License

MIT
