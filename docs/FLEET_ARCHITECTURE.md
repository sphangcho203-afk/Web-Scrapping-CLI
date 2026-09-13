# Internet Hands Fleet Architecture

Internet Hands now has two crawl execution planes:

1. `ih-hunt` for bounded single-process collection.
2. `ih-fleet` / `ih-worker` for durable multi-process or multi-machine collection.

Both use the same `FetchResult`, extraction, provenance, and indexing contracts. Fleet mode changes scheduling and storage topology without creating a second crawler model.

## Distributed flow

```text
seed URLs / search seeds / fleet API
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
       + telemetry events
              |
      +-------+---------+---------+
      |                 |         |
      v                 v         v
 native HTTP         Crawlee   Crawl4AI
      |                 |         |
      +-----------------+---------+
                        |
                      Scrapy
                        |
                        v
             normalized FetchResult
                        |
              extraction + discovery
                        |
          +-------------+-------------+
          |                           |
          v                           v
   capture metadata               raw bytes
 Postgres or SQLite           S3/MinIO or local
          |                           |
          +-------------+-------------+
                        |
               searchable documents
                        |
               enqueue child URLs
```

## Local fleet

The default local frontier is `.internet-hands/frontier.db`. SQLite uses WAL plus atomic leasing so multiple local worker processes do not process the same URL simultaneously.

Local content storage remains `.internet-hands/internet-hands.db` plus the content-addressed `.internet-hands/objects/` directory. Local telemetry defaults to `.internet-hands/telemetry.db`.

Example:

```bash
ih-fleet seed https://example.com --scope origin

ih-fleet run-once --worker-id local-1 --batch-size 16

ih-worker --worker-id local-long-running --batch-size 16

ih-fleet stats
ih-fleet events --follow
```

Multiple local workers share per-host reservation state, so adding processes does not multiply request pressure to the same host.

## Distributed frontier

Set:

```bash
export INTERNET_HANDS_POSTGRES_DSN='postgresql://user:pass@postgres/internet_hands'
```

The Postgres frontier uses `FOR UPDATE SKIP LOCKED` to lease distinct jobs across many worker nodes. It also stores retry state, lease expiry, distributed circuit-breaker state, and shared per-host request reservations.

## Shared capture and index storage

Set a shared metadata database:

```bash
export INTERNET_HANDS_CONTENT_POSTGRES_DSN='postgresql://user:pass@postgres/internet_hands'
```

and S3-compatible raw object storage:

```bash
export INTERNET_HANDS_S3_BUCKET='internet-hands'
export INTERNET_HANDS_S3_PREFIX='internet-hands/objects'
export INTERNET_HANDS_S3_ENDPOINT_URL='https://s3.example.com'  # omit for AWS S3
export AWS_ACCESS_KEY_ID='...'
export AWS_SECRET_ACCESS_KEY='...'
export AWS_REGION='us-east-1'
```

Distributed capture mode deliberately requires a shared S3-compatible bucket. It will not silently write raw response bytes to a worker-local filesystem while metadata goes to shared Postgres.

Postgres stores:

- request/final URL
- status and content metadata
- SHA-256 provenance
- timing and capture timestamp
- response headers as JSONB
- S3 object location
- normalized documents, headings, and links
- generated PostgreSQL `tsvector` search data with a GIN index

Raw bytes are content-addressed by SHA-256 and stored under an object key similar to:

```text
internet-hands/objects/2c/2cf24dba5f...
```

Shared search and capture inspection are available through `ih-content` and the fleet API.

```bash
ih-content search "distributed crawlers"
ih-content stats
ih-content recent --limit 25
```

## Telemetry event stream

Workers emit durable events such as:

- `batch_started`
- `job_started`
- `job_skipped_robots`
- `capture_saved`
- `job_completed`
- `job_failed`
- `job_deferred_circuit`
- `batch_completed`
- `worker_idle`

Telemetry is non-critical: failure to record an event never fails the crawl job itself.

For a shared event stream:

```bash
export INTERNET_HANDS_TELEMETRY_POSTGRES_DSN='postgresql://user:pass@postgres/internet_hands'
ih-fleet events --follow
```

The distributed control API also exposes authenticated Server-Sent Events at:

```text
GET /v1/events/stream
```

Clients can reconnect with `after_id` to resume from the last durable event ID.

## Fleet control API

Run:

```bash
export INTERNET_HANDS_API_KEY='replace-me'
ih-fleet-api
```

Default bind: `0.0.0.0:8788`.

Key endpoints:

```text
GET  /healthz
GET  /v1/frontier/stats
POST /v1/frontier/seed?url=https://example.com
GET  /v1/content/stats
GET  /v1/content/recent
GET  /v1/search?q=example
GET  /v1/events
GET  /v1/events/stream
```

The API fails closed when `INTERNET_HANDS_API_KEY` is absent unless trusted local unauthenticated mode is explicitly enabled.

## Long-running workers

`ih-worker` is the container/server entrypoint. Unlike `ih-fleet drain`, it remains alive when the queue is temporarily empty.

```bash
ih-worker --batch-size 32 --idle-seconds 5
```

Workers discover frontier/content/telemetry/S3 configuration from environment variables. This lets the same image scale horizontally without per-node config files.

## Retry and circuit policy

Worker failures are recorded as queue state, not swallowed. Retries use exponential backoff with jitter. Once a job reaches `max_attempts`, it moves to `dead` rather than retrying forever.

Circuit breakers are keyed by backend and host. Repeated failures temporarily defer new attempts; a successful request resets the circuit.

## Backend execution

Fleet workers can use:

- `native` — Internet Hands HTTP fetcher with public-DNS and connected-peer validation.
- `crawlee` / `crawlee-http` — Crawlee HTTP adapter.
- `crawl4ai` — Crawl4AI browser renderer/extractor adapter.
- `scrapy` — Scrapy worker adapter with redirects disabled and robots enabled.

External engines require explicit opt-in:

```bash
ih-worker --backend crawl4ai --allow-external-network
```

Those engines should run in public-egress-restricted containers because they own part of their network stack.

## Network hardening

The native HTTP path validates public DNS before requests and, when exposed by the transport, validates the connected peer address again. Redirect targets are revalidated.

Production must still enforce public-only egress at the container/VM/network layer. Application URL checks are defense in depth, not a replacement for network policy.

## Container deployment

The repository includes:

```text
Dockerfile.fleet
deploy/docker-compose.fleet.yml
```

Start a single worker plus infrastructure:

```bash
docker compose -f deploy/docker-compose.fleet.yml up --build
```

Scale workers horizontally:

```bash
docker compose -f deploy/docker-compose.fleet.yml up --build --scale worker=4
```

The Compose stack provides:

- PostgreSQL for frontier, shared metadata/search, and telemetry
- MinIO for S3-compatible raw objects
- authenticated fleet API on port `8788`
- one or more long-running workers
- optional tools container via the `tools` profile

Change all example passwords/API keys before exposing the stack outside a development machine.

## Exports

WARC:

```bash
ih-export warc data/crawl.warc.gz
```

Parquet:

```bash
pip install -e '.[parquet]'
ih-export parquet data/documents.parquet
```

The current WARC/Parquet exporter reads the local SQLite capture store. A direct distributed Postgres/S3 export path remains a follow-on task; shared collection/search itself is already implemented.

## Failure semantics

A frontier job has four terminal/working states:

- `queued`: eligible for a future lease after `available_at`
- `leased`: temporarily owned by one worker
- `done`: successfully handled or intentionally skipped by policy/robots
- `dead`: attempt budget exhausted

`ih-fleet stats` exposes these counts directly.

## Current scale boundary

The major single-node storage boundary is removed: frontier coordination, capture metadata, document search, raw response objects, and worker telemetry can all be shared across machines.

Remaining production work is mostly operational depth rather than a storage rewrite: schema migrations, lifecycle/retention policy, object versioning, metrics/alerts, distributed export jobs, network-policy templates, and deployment targets beyond Docker Compose.
