# Internet Hands architecture

Internet Hands v0.2 separates collection, evidence preservation, extraction, indexing, and monitoring. A platform-specific collector should not need to reimplement network policy or provenance.

## Core layers

1. **Policy** — validates public HTTP(S) targets and blocks non-public address space.
2. **HTTP fetcher** — captures redirects, status, headers, timing, SHA-256, decoded text, and exact bytes.
3. **Browser worker** — optional Playwright renderer with per-request target filtering.
4. **Extractor** — derives title, description, headings, readable text, and links from captures.
5. **Crawler / pipeline** — bounded same-origin traversal that can write directly to the index.
6. **Object store** — content-addressed raw bodies keyed by SHA-256.
7. **SQLite index** — capture metadata, extracted documents, FTS5 search, watches, and events.
8. **Monitor scheduler primitive** — durable watch definitions plus a `run due jobs` execution model.
9. **Adapter registry** — extension point for public or explicitly authorized platform collectors.
10. **Interfaces** — Typer CLI and FastAPI control API.

## Flow

```text
             ┌───────────────┐
             │ CLI / FastAPI │
             └───────┬───────┘
                     │
              ┌──────▼──────┐
              │ URL policy  │
              └───┬─────┬───┘
                  │     │
          ┌───────▼┐   ┌▼──────────────┐
          │ HTTP   │   │ Browser       │
          │ worker │   │ worker        │
          └────┬───┘   └──────┬────────┘
               └──────┬────────┘
                      ▼
               source capture
             status/headers/body
                 timing/SHA-256
                      │
              ┌───────▼────────┐
              │ object storage │
              └───────┬────────┘
                      │
                ┌─────▼─────┐
                │ extractor │
                └─────┬─────┘
                      │
             ┌────────▼────────┐
             │ SQLite + FTS5   │
             └───┬────────┬────┘
                 │        │
              search    watches
                 │        │
                 └───┬────┘
                     ▼
              export / agents
```

## Persistent monitoring

A watch stores a URL, interval, next-run timestamp, last hash, and last check. `ih watch run` processes only jobs whose `next_run_at` is due. That makes the scheduler composable: cron, systemd, Kubernetes CronJob, a queue worker, or another orchestrator can invoke the same primitive without Internet Hands needing a permanently running daemon.

Each successful watch run is also indexed, so a monitored source naturally builds historical capture data instead of throwing old checks away.

## Object storage

Raw response bodies are stored under a SHA-256-derived path. Identical content is written once and can be referenced by multiple capture rows. Exact response bytes are preserved even when a decoded text representation is also available.

## Search

Extracted documents are inserted into SQLite FTS5. Search results retain document IDs, source URLs, capture times, SHA-256 values, and snippets, preserving the path from a search result back to the underlying evidence.

## Adapter SDK

Adapters implement two operations:

- `supports(url)` — whether the adapter is intended for the target;
- `collect(url)` — return a source result while retaining provenance.

The built-in registry starts with generic HTTP and JSON API adapters. Future platform adapters should prefer official/public APIs when they exist, document rate limits, and point normalized records back to their raw captures.

## Browser boundary

A browser is more dangerous than an HTTP client because page JavaScript can initiate requests independently. The worker therefore installs a request route that applies the same public-target validation to subresources before allowing them to continue.

For production, run browser workers in separate containers with network-level egress policy as a second boundary. Application-level URL validation alone is not a substitute for infrastructure isolation.

## Next architecture step

The next major phase is a queue-backed worker system:

```text
Control API -> queue -> HTTP/browser workers -> object store -> Postgres/search -> events
```

That phase should also add DOM/text/header diffing, WARC import/export, signed manifests, and a dashboard for captures, watches, search, and provenance graphs.
