# Internet Hands Fleet Architecture

Internet Hands has two crawl execution planes:

1. `ih-hunt` for bounded single-process collection.
2. `ih-fleet` for durable multi-process or multi-machine collection.

Both feed the same capture/extraction/index model. The fleet layer changes how crawl work is scheduled; it does not create a second provenance model.

## Worker flow

```text
seed URLs / search seeds
          |
          v
 durable frontier
  SQLite or Postgres
          |
    atomic lease
          |
          v
      crawl worker
   + host pacing
   + robots policy
   + circuit breaker
          |
    +-----+----------------------+----------------+
    |                            |                |
    v                            v                v
 native HTTP                 Crawlee          Crawl4AI
    |                            |                |
    +----------------------------+----------------+
                                 |
                              Scrapy
                                 |
                                 v
                    normalized FetchResult
                                 |
                     extraction + discovery
                                 |
              capture objects + SQLite/FTS index
                                 |
                 enqueue bounded child URLs
```

## Local fleet: SQLite

The default fleet frontier is `.internet-hands/frontier.db`.

SQLite fleet mode uses WAL plus `BEGIN IMMEDIATE` to make leasing and host-slot reservation atomic across local worker processes. A job has:

- canonical URL
- root URL and scope
- depth and parent
- priority
- queued / leased / done / dead state
- attempt counter and max-attempt budget
- next-available timestamp
- lease owner and lease expiry
- last error

A worker lease is temporary. If a process crashes, an expired lease is returned to the queue unless its attempt budget has been exhausted.

Example:

```bash
ih-fleet seed https://example.com --scope origin

ih-fleet run-once --worker-id local-1 --batch-size 16

ih-fleet drain --worker-id local-2 --batch-size 16

ih-fleet stats
```

Multiple local workers share persistent per-host request slots, so adding workers does not multiply request pressure to the same hostname.

## Distributed fleet: Postgres

Set:

```bash
export INTERNET_HANDS_POSTGRES_DSN='postgresql://user:pass@host/dbname'
```

Install the optional dependency:

```bash
pip install -e '.[postgres]'
```

Then use the same CLI:

```bash
ih-fleet seed https://example.com --scope origin

ih-fleet drain --worker-id worker-a --batch-size 32
```

The Postgres frontier uses `FOR UPDATE SKIP LOCKED` when leasing work. This allows workers on separate machines to lease distinct jobs without a central scheduler bottleneck.

Postgres also stores distributed circuit-breaker state and per-host reservation timestamps.

The content/index store is still the existing Internet Hands SQLite/object-store path in this branch. Postgres currently coordinates the frontier, retries, circuit state, and pacing; it is not yet the primary capture/document database.

## Retry and circuit policy

Worker failures are recorded as queue state, not swallowed.

Retries use exponential backoff with jitter. Once a job reaches `max_attempts`, it moves to `dead` instead of retrying forever.

Circuit breakers are keyed by backend and host. Repeated failures temporarily stop new attempts for that backend/host combination. A successful request resets the circuit.

This protects both the operator and the remote service from tight failure loops.

## Backend execution

Fleet workers can use:

- `native` — Internet Hands HTTP fetcher with public-DNS and connected-peer validation.
- `crawlee` / `crawlee-http` — Crawlee `HttpCrawler` adapter.
- `crawl4ai` — Crawl4AI browser renderer/extractor adapter.
- `scrapy` — one-request Scrapy worker adapter with redirects disabled and robots enabled.

Native mode is the default.

External engines require explicit opt-in:

```bash
ih-fleet drain \
  --backend crawl4ai \
  --allow-external-network
```

This switch is intentionally noisy. Browser/crawler libraries may perform their own redirects, subresource loads, session work, or other network activity outside the native HTTP transport. In production they should run in containers or sandboxes whose network policy blocks private, loopback, link-local, metadata-service, and other non-public destinations.

The application-level URL checks are defense in depth, not a replacement for egress policy.

## Network hardening

The native HTTP path records a public DNS resolution snapshot before connecting. When the HTTP transport exposes the connected server address, Internet Hands validates that peer IP again and stores it with the capture provenance.

This catches a meaningful class of DNS-rebinding/SSRF transitions from public hostname to private peer.

Production should still enforce public-only egress at the container/VM/network layer because an application cannot guarantee perfect DNS pinning for every third-party transport or browser stack.

## Exports

WARC:

```bash
ih-export warc data/crawl.warc.gz
```

The WARC writer emits WARC/1.1 response records with target URI, capture date, payload SHA-256, stored HTTP headers, and captured body bytes.

Parquet:

```bash
pip install -e '.[parquet]'
ih-export parquet data/documents.parquet
```

Parquet contains normalized document text plus capture metadata and uses Zstandard compression.

## Failure semantics

A fleet operator should expect four states:

- `queued`: eligible for a future lease after `available_at`.
- `leased`: temporarily owned by one worker.
- `done`: successfully handled or intentionally skipped by policy/robots.
- `dead`: attempt budget exhausted.

`ih-fleet stats` exposes these counts directly.

## Scale boundaries

Current fleet mode solves durable scheduling, cross-worker coordination, retries, pacing, circuit state, backend routing, and portable exports.

The remaining scale boundary is capture storage itself. A very large deployment should move capture/document metadata and object storage to a shared database/object store while retaining the same `FetchResult` and provenance contracts.
