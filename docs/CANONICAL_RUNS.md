# Canonical run receipts — Wave 1, first slice

The existing usage request ID is the canonical run ID. `ih_runs` is an additive,
account-owned receipt and `ih_run_events` records committed billing and specialized execution transitions.
Wallet settlement, leases, provider state and cancellation stay in their existing
stores. No new charging path is introduced.

- `GET /api/runs?limit=25&offset=0` lists owned receipts.
- `GET /api/runs/{request_id}?after=0&limit=100` returns a receipt, saved dataset
  reference, specialized crawl/extract execution state and bounded event page.
- Session authentication or an API key with `mcp:read` (or `*`) is required.
- Foreign and missing receipts return the same 404. Private metadata, provider job
  identifiers, arguments and credentials are excluded.

The usage inspector displays reservation versus charge, saved output, specialized
attempts/cancellation state and recorded billing events. Older deployments retain
the usage inspector with an explicit receipt-unavailable message.

Schema installation follows the existing control-store migration path. The usage
trigger executes in the same transaction as reservation/settlement: rollback removes
both the receipt change and its event. The run row serializes event sequence allocation.
Repeating unchanged settlement creates no extra event. Historical ledger rows are
backfilled without fictional events or completion timestamps. The receipt `status`
and `finished_at` describe **billing**, not transport/data quality; specialized
execution state is returned separately.

## Remaining Wave 1 work

This is not the complete canonical execution model. Quote-only requests have no run
until reservation. Detailed progress events and parent/workflow lineage,
warning/source summaries, normalized execution status and provider-attempt timelines
remain to be bridged. Crawl and capability job status/attempt/cancellation changes are recorded atomically by specialized table triggers. Internal actual/estimated COGS are not fabricated. No production
verification or profitability claim follows from this receipt implementation.
