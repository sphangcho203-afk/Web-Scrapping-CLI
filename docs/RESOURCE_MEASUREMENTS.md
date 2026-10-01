# Dataset payload and webhook attempt evidence

## Decision and units

Saved output and delivery now contribute application measurements to the private
run economics report. These facts have no USD valuation. Physical database
allocation, storage duration, network transfer and invoice costs remain unknown.
`summary.coverage` is `partial`; complete COGS and margin remain unknown.

`ih_dataset_payload_measurements` records one observation per dataset. Its byte
quantity is the sum of the UTF-8 lengths of PostgreSQL's `columns::text`,
`rows::text` and `output::text` JSONB representations. Both the extracted rows and
original output count because both are stored. Dataset names and other metadata
are excluded. Compression, TOAST, indexes, replication, temporary outputs and
exports are unmeasured. This is an observed payload volume, not current physical
storage, peak allocation or byte-hours. Renaming does not change the observation.

An insert trigger captures new output in the dataset/outbox transaction. A failed
save or rollback leaves no fact. Re-saving the same request preserves the first
observation. Schema installation snapshots surviving older datasets once, marking
them `existing_snapshot` rather than inventing an insertion-time measurement.
Previously deleted artifacts and their past retention cannot be reconstructed.

## Webhook claim, intent and outcome

`ih_webhook_attempt_measurements` journals each new lease, atomically with the
claim. Identity is delivery ID plus lease token; the automatic attempt ordinal is
insufficient because manual retry resets it. The journal records exact UTF-8 body
length, run identity, ordinal and claim time, followed by optional dispatch intent
and outcome. It retains no body, endpoint URL, secret, signature or response body.
Lease tokens are internal fencing identifiers and never appear in the report.

The dispatcher prepares the body/signature and commits one intent while it owns
a live lease, before calling the sender. Concurrent or expired attempts cannot
commit another intent or invoke the sender. Live-lease validation uses the actual
clock after taking the delivery lock. A transaction's start time cannot authorize
a send after lock contention outlives the lease.

An intent measures the application payload offered to the send path. DNS/policy
rejection, connection failure and a crash before HTTP invocation may transfer no
bytes. An intent therefore does not establish actual wire egress. Header/TLS
overhead, receiver response traffic, HTTP retries and dataset downloads remain
unmeasured. Preparation failures can have a recorded outcome without an intent.

The first recorded outcome for an attempt is immutable. A late worker can record
its own outcome without overwriting a newer outbox lease. Two observed successful
responses can belong to one delivery event: receivers must still deduplicate.
Automatic retry and manual replay create additional journal entries, preserving
each application's byte quantity without charging another collection.

A crash or failed outcome write leaves an unknown outcome. Lease recovery does
not turn the abandoned attempt into success, failure or zero transferred bytes.
Claims without intents and unfinished intents are counted separately. Old leases,
prior attempts, manual retries and expired history are not reconstructed from the
outbox counter. Historical coverage remains `not_reconstructed` even when all
newly journaled attempts have outcomes.

## Operator read contract

Use the existing service-token / authorized GitHub OIDC interface:

```sh
curl --fail-with-body "$OPENCRAWL_URL/api/internal/runs/$RUN_ID/economics" \
  -H "Authorization: Bearer $OPENCRAWL_OPERATOR_TOKEN"
```

All aggregates are read from one repeatable-read database snapshot and cover the
run, independent of provider-event pagination. Decimal byte totals retain exact
precision as JSON strings. Counts are integers. Responses use `no-store`.

| Coverage | Evidence |
| --- | --- |
| `storage` | Observed dataset count, insert/snapshot origin counts, `observed_jsonb_utf8_bytes`, current surviving observed datasets and current datasets missing measurements |
| `delivery` | Claim, intent, outcome, unknown-outcome and unfinished-intent counts; delivered/retry/failed outcome counts; outcomes without HTTP status; claimed and dispatch-intent payload UTF-8 byte totals; current delivery events without a journal |

Both dimensions report `state: partial`, `valuation_state: unknown` and
`historical_coverage: not_reconstructed`. Zero observed facts means zero recorded
evidence, not proof of no past storage or traffic. A delivery without a journal
may be pending or pre-instrumentation; that count is not a failure count.
`delivered_count` counts attempt outcomes, not unique events or business effects.
Browser measurements remain under browser coverage; model, compute and proxy
remain uninstrumented. Sourced provider-credit valuation remains independent.
Customer Runs/Datasets/delivery APIs do not expose these operator facts.

## Lifecycle, migration and rollback

The two tables are additive and indexed by canonical run. Dataset/delivery IDs
have no foreign key to deletable output/history. Dataset deletion, endpoint removal
and the outbox's 30-day cleanup preserve observations; the current dataset count
can decrease while the observed payload total stays unchanged. Canonical run or
account deletion cascades to remove the journal and payload observations.

Schema reinstall preserves observations, intents and outcomes. Database guards
reject payload-observation updates, claim changes, replaced intents and replaced
outcomes. No operator write API edits these facts. Retention for this audit data
follows the canonical run lifecycle rather than the shorter delivery history.

Older application revisions can ignore the tables. Their claim path still
produces claim facts through the trigger but has no dispatch-intent/outcome
instrumentation; reports expose those gaps. To stop all new resource capture,
pause writers, roll back the application, then disable `ih_dataset_payload_capture`
and `ih_webhook_claim_capture`. Preserve the evidence tables. Disable capture only
after rolling back: the current dispatcher requires a journal entry before sending.
Reinstalling the current schema recreates capture triggers.

Real PostgreSQL tests cover UTF-8 bytes, duplicates, transaction rollback, snapshots,
schema reinstall, concurrent intents, stale leases, missing outcomes, manual replay,
policy rejection, deletion/cascades, immutability and operator/customer boundaries.
Mocks exercise HTTP outcomes; no real external receiver is contacted. Authenticated
production execution, signed delivery and invoice reconciliation remain unverified.
