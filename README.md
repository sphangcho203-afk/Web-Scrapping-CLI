# 🥷 Internet Hands — Web Scrapping CLI

**Raw internet intelligence, end to end.**

**Internet Hands** is the engine inside **Web-Scrapping-CLI** — an open-source toolkit for collecting and inspecting public web data without hiding what happened between your command and the network. It is designed for researchers, developers, defenders, journalists, operators, and anyone who needs repeatable visibility into HTTP resources.

> Fetch the bytes. Keep the evidence. Understand the change.

## What it does

- **Raw fetch** — status, headers, body, redirects, hashes, timing, and provenance.
- **Link extraction** — discover and normalize links from HTML pages.
- **API inspection** — call JSON/text APIs and preserve the exact response envelope.
- **Crawler** — bounded, same-origin crawling with deduplication and optional robots.txt checks.
- **Web monitor** — snapshot a URL and detect content changes by cryptographic hash.
- **Health checks** — availability, latency, response status, content type, and TLS-visible endpoint behavior.
- **Download preparation** — inspect a public file before retrieving it: filename, size, content type, disposition, and source URL.
- **Artifact store** — every run can produce a machine-readable manifest plus captured body data.
- **Local API** — expose the engine through FastAPI for your own tools and agents.

## Why this exists

Most scraping tools jump straight to parsed content. Internet Hands keeps the lower-level evidence too: request URL, final URL, response headers, content hash, capture timestamp, and exact response bytes. That makes results easier to verify, diff, reproduce, and audit.

It is intentionally modular. Platform-specific adapters can sit on top of the same fetch/capture pipeline instead of becoming one-off scripts.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

ih fetch https://example.com
ih links https://example.com
kh="https://api.github.com/repos/python/cpython"
ih api "$kh"
ih health https://example.com
```

Capture a response to disk:

```bash
ih fetch https://example.com --save
```

Crawl a public site, bounded to the same origin:

```bash
ih crawl https://example.com --max-pages 25 --respect-robots
```

Create or compare a monitoring snapshot:

```bash
ih monitor https://example.com --state .internet-hands/example.json
```

Run the local API:

```bash
export INTERNET_HANDS_API_KEY='change-me'
ih serve --host 127.0.0.1 --port 8787
```

Then call:

```bash
curl -H "X-API-Key: change-me" \
  'http://127.0.0.1:8787/v1/fetch?url=https%3A%2F%2Fexample.com'
```

## Architecture

```text
CLI / Local API / future UI
          │
          ▼
   Request policy layer
   ├─ URL validation
   ├─ private-network blocking
   ├─ timeout/body limits
   └─ robots policy for crawl
          │
          ▼
      Fetch engine
   ├─ redirects
   ├─ raw bytes
   ├─ headers/status
   ├─ timing
   └─ SHA-256
          │
          ├────────► parsers / link graph
          ├────────► monitor / diff state
          └────────► artifact manifests
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the roadmap.

## Safety model

Internet Hands is powerful because it works close to the network layer, but it is not designed to defeat access controls. The default policy:

- blocks localhost, link-local, and private-network targets to reduce SSRF risk;
- only supports `http` and `https` URLs;
- limits response sizes and timeouts;
- keeps crawling bounded and same-origin;
- can honor `robots.txt` for crawling;
- does not include credential theft, CAPTCHA bypass, auth bypass, exploit delivery, or stealth/evasion logic.

If a source needs authentication, use an official API or a session/token you are authorized to use in a dedicated adapter.

## Roadmap

- [x] Raw fetch + provenance
- [x] Link extraction
- [x] API inspection
- [x] Same-origin crawler
- [x] Change monitoring
- [x] Health checks
- [x] Download metadata inspection
- [x] FastAPI service
- [ ] Scheduled monitors + event stream
- [ ] SQLite/Postgres artifact index
- [ ] Browser-rendered pages through an isolated Playwright worker
- [ ] Platform adapter SDK
- [ ] Content extraction pipelines
- [ ] Search/index layer
- [ ] Web dashboard with capture graph and diffs
- [ ] Distributed workers and queues
- [ ] Export bundles: JSONL / WARC / Parquet
- [ ] Signed provenance manifests

## Repository

GitHub: `sphangcho203-afk/Web-Scrapping-CLI`

## License

MIT
