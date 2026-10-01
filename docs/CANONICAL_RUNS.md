# Canonical runs — Wave 1

The existing billing request ID is the canonical run ID. `ih_runs` extends the
account-owned receipt with an execution envelope; `ih_run_events` records facts in
the same database transaction as billing, specialized execution and output writes.
Wallet settlement, worker leases, provider state and cancellation remain owned by
the existing stores. No second charging path is introduced.

## API and dashboard

- `GET /api/runs?limit=25&offset=0` lists owned runs.
- `GET /api/runs/{id}?after=0&limit=100` returns the envelope, specialized execution
  state, dataset reference and bounded event page. Use `next_after` for subsequent
  pages. The canonical request ID and legacy specialized job ID both resolve.
- `POST /api/runs/{id}/cancel` delegates to the existing specialized store.
  Active crawl cancellation is cooperative; captured work may be charged. Extract
  cancellation is supported only while queued. Started extraction returns
  `run_already_started`; immediate calls return `run_not_cancellable`.
- Read access requires a session or API key with `mcp:read` (or `*`); cancellation
  requires `mcp:execute`. Foreign and missing runs return the same 404. Responses
  use `Cache-Control: no-store`.
- `/dashboard/runs` provides a paged history and responsive inspector with live
  polling, cancellation, quote/billing reference and dataset links. The existing
  Usage inspector and specialized routes remain compatible.

```sh
curl "$OPENCRAWL_URL/api/runs/$RUN_ID?after=0&limit=100" \
  -H "Authorization: Bearer $OPENCRAWL_API_KEY"
```

`status` retains the billing ledger contract. `execution_status` is normalized to
created / queued / running / waiting / completed / partial / failed / cancelled.
Partial crawl output is distinguished from the successful billing state. Schema
validation warnings do not turn successful transport into failed execution.
Quote-only requests do not create a run; the quote revision links confirmed work
back to its reviewed price. Immediate runs record reservation and settlement;
there is no fictional worker-start event.

## Additive storage

`run_projection.SCHEMA` adds execution source/ref, version, monitor, dataset,
source count, observed start/finish, measured duration, retries, warnings,
cancellation and error fields to the existing receipt schema. Parent/workflow/live
Dataset references are nullable seams for future producers. Internal estimated and
actual cost columns remain NULL until real cost events exist, and are excluded
from public reads.

Usage triggers bridge all billed execution paths, including Playground search,
Smart Scrape, Site Map, public data, gaming and MCP. Crawl and Structured Extract
triggers bridge durable state. Content monitors inherit their crawl run identity.
Unbilled legacy HTTP health probes remain monitor history, not billed run receipts.
Only bounded source counts enter usage metadata; inputs and credentials are not
copied into the envelope. Recorded provider attempts expose outcome and attempt
number, never provider IDs, routing refs, raw errors or credential material.
Provider attempt timestamps mark persistence during settlement, not a fabricated
start time.

The run row serializes sequence allocation. Rollback removes projected fields and
events together; duplicate settlement produces no extra charge or billing event.
Historical facts are imported without invented events or completion/start times.
Reinstalling the migration preserves event history. Dataset deletion removes the
output reference through its FK and does not retain captured data in run events.

## Verification and limits

PostgreSQL regression coverage exercises concurrent idempotent creation, fenced
recovery, rollback, partial output, immediate settlement, private attempt data,
waiting extraction, cancellation rules, API scopes, foreign ownership and repeated
migration installation. Chromium exercises history navigation, timeline paging,
cancellation and overflow at 320/390/1366px. The target-specific extraction claim
now types its nullable PostgreSQL parameter explicitly.

Production authenticated provider execution, export/settlement, scheduler behavior
and controlled signed webhook delivery remain **not verified**. Detailed progress
checkpoints, quote-only identity and populated workflow/live Dataset parentage
remain future work. These run records do not claim a data-health or COGS engine.
