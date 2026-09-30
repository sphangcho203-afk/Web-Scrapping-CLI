# Background crawl runs

Enable **Background URL crawl** in Playground, enter a public URL and submit. The request reserves credits and returns an owned job immediately. Open **Background crawls** to reopen progress, cancel collection or follow its saved dataset. Closing the page does not cancel the job. The existing synchronous Playground endpoint remains available.

## Public contract

- `POST /api/crawl-runs`: the same execution credentials and crawl controls as Playground, with an `Idempotency-Key` header. Session callers select an owned active `api_key_id`. Execution credentials need `mcp:execute`.
- `GET /api/crawl-runs?limit=25&offset=0` and `GET /api/crawl-runs/{id}`: account-owned history and progress; API credentials need `mcp:read`.
- `POST /api/crawl-runs/{id}/cancel`: execution permission required. Foreign run IDs return 404.

Responses never expose leases, credentials, account IDs or checkpoint content. They are marked `Cache-Control: no-store`. The create response is HTTP 202 and contains `run.id`, `request_id`, status, progress and reserved credits. Supply the same key and normalized inputs after a lost response; the returned job and reservation are the same. Reusing the key with different inputs returns 409. Keys contain 1–128 ASCII letters, digits, `.`, `_`, `:` or `-` and remain associated with their run.

Example body: `{"url":"https://example.com/","max_pages":12,"max_depth":2,"concurrency":4,"max_seconds":30}`. Optional path arrays, subdomain/query controls and content options match the crawler. Background limits are 1–50 pages, depth 0–4, concurrency 1–6, 5–45 seconds, readable content at most 50 KB per page and 500 KB total. Invalid values are rejected before a reservation. Robots and existing public-target checks remain enforced during collection.

## Lifecycle and recovery

`queued → running → completed / failed / cancelled`. A repository-scoped OIDC scheduler calls the protected `/api/internal/crawl-runs/tick` independently of monitor and webhook jobs every five minutes. Each tick claims one job using PostgreSQL `FOR UPDATE SKIP LOCKED`, and performs at most the remaining original crawl time budget (with a 50-second worker ceiling). Queued jobs normally start within five minutes when capacity is available; this initial dispatcher handles at most one job per tick. Preview needs an authorized manual tick and does not receive production schedules.

Each attempt has a unique 90-second lease. Expired attempts can be claimed again once. Checkpoints persist after each batch: page captures, ordered pending URLs, completed request URLs and measured native requests are committed together. The replacement worker restores them from the database. Late workers cannot checkpoint or finalize after their lease expires or is replaced. The second lost attempt terminates with `worker_lost`, preserving the last checkpoint as a partial dataset. Jobs expire after 24 hours and close when a dispatcher tick observes the expiration. If the scheduler is unavailable, queued reservations remain held until cancellation or a later tick.

Recovery **resumes the saved account-owned frontier** and preserves committed captures. It does not fetch completed request URLs again. A crash during a batch can repeat its uncommitted HTTP requests; this is at-least-once collection, not exactly-once network delivery. Robots policies and existing public-target checks are refreshed for pending work. Page, depth, readable-content and elapsed-work budgets carry forward across attempts. A versioned control hash prevents resuming with different bounds or scope. Invalid frontier state terminates visibly with `invalid_checkpoint` rather than silently recollecting from the seed.

The frontier accepts at most 1000 distinct request URLs, 500 KB of URL bytes total and 4096 bytes per URL. Links exceeding these limits are skipped and `frontier_truncated` is visible in output and job progress. New checkpoints include this state; legacy jobs with capture-only checkpoints restart from their seed once. Terminal jobs discard private frontier state along with full checkpoint content. This release still does not run JavaScript browsers, support asynchronous search/research or split a large crawl across scheduled time slices. The existing global fleet frontier remains separate from account-owned jobs.

## Billing, cancellation and output

Creation, usage reservation and job insertion share one transaction. Finalization saves the dataset, enqueues its webhook event, settles the existing wallet/ledger and changes the job to terminal in one transaction. Failure rolls everything back and leaves recovery possible. Repeated submissions, workers or completions never create a second customer reservation or settlement. Recovery work remains within the original reservation, and persisted usage counters carry forward. Requests made before a crash but not included in a committed checkpoint may be absent from those counters; retries do not create another customer charge.

The current `playground:crawl` measured-pricing policy charges one raw completion credit for successfully fetched output or successful captured partial work, converted by the existing wallet multiplier and bounded by the original reservation. Native request counters are recorded for accounting. A crawl with no successful 2xx pages terminates as failed with `no_successful_pages`, releases its completion charge and reports successful/failed page counts. Diagnostic records may still be saved. Queued cancellation and failure without successful output release the full reservation. Cancelling running work is cooperative at the next completed batch or finalization: fetched partial records remain saved and may be charged. It does not promise to interrupt in-flight HTTP requests immediately. Content monitors reuse these jobs with their own readable-content comparison and history; see [CONTENT_MONITORS.md](CONTENT_MONITORS.md).

The dataset records `run_status`, page errors and truncation flags. Dataset limits remain 2 MB / 1000 rows. Oversized output terminates visibly with `output_limit_exceeded`, releases the reservation and does not claim saved data. Once terminal, the job retains progress metadata rather than a duplicate of page text. Deleting a dataset clears its run link and associated webhook event while preserving billing history.

## Verification and release gate

Real isolated PostgreSQL tests cover concurrent duplicate creates, conflicts, stale-worker fencing, cancellation, expiry, transaction rollback, recovered partial output, output limits, normal worker execution, dataset deletion and replacement-process frontier recovery. Crawler fixtures cover committed-page reuse, in-flight repeats, carried time/content bounds, refreshed robots policies and bounded fan-out. Chromium exercises background submission, reopening and cancellation on mobile and desktop. Existing dataset/webhook, wallet, metering and Playground tests must remain green.

This implementation is reviewable on the existing draft PR. Before production promotion, verify an authenticated create → protected tick → completed job → saved/exported records flow on the deployed environment, followed by duplicate submission, cancellation and optional external webhook receipt. Local provider fixtures and build readiness do not establish that production flow.
