# Sourced provider rates and measurement coverage

## Decision and scope

Provider-reported credits are measurements, separate from customer credits. An
operator can import an exact USD price for a specific provider, operation and
`provider_credit` unit. No prices are seeded. A rate must have a source reference,
source as-of timestamp and explicit validity window. These valuations are rate
estimates; they do not establish reconciled invoice expense or complete run COGS.
Wallet settlement, quote prices and reservation-time conversion remain unchanged.

`ih_cost_rates` stores immutable, content-addressed revisions and an increasing
version. Repeating the same normalized import returns the same revision. Revisions
are serialized per provider/operation/unit. Among overlapping valid revisions,
the highest imported version wins for a newly recorded event. The event pins that
revision, source and price; later imports never reprice it. Append a sourced
revision when a contract changes.

Validity uses the persisted measurement event's timestamp. The start is inclusive
and the end exclusive. Provider invoice-time attribution is not implemented.
An expired, future or operation-mismatched rate leaves a new event unpriced.
Historical events stay unchanged until an operator explicitly values them.

## Operator API

All routes require the existing authorized service token or GitHub OIDC boundary.
Customer sessions and API keys cannot import or read private prices. Decimal
amounts are JSON strings and responses use `Cache-Control: no-store`.

`POST /api/internal/cost-rates` accepts exactly these fields:

| Field | Contract |
| --- | --- |
| `provider`, `operation` | Lowercase identifier, at most 80 characters; must match measured usage |
| `unit` | `provider_credit` |
| `unit_cost_usd` | Nonnegative decimal **string**, below 1,000,000, at most 12 decimal places |
| `source_reference` | Nonempty single-line invoice/contract/pricing reference, at most 512 characters |
| `source_as_of` | ISO timestamp with timezone, no later than import time |
| `effective_from`, `effective_until` | ISO timestamps with timezone; positive validity interval |

Create `provider-rate.json` from the actual sourced contract, then import it:

```sh
curl --fail-with-body "$OPENCRAWL_URL/api/internal/cost-rates" \
  -H "Authorization: Bearer $OPENCRAWL_OPERATOR_TOKEN" \
  -H 'Content-Type: application/json' --data-binary @provider-rate.json

curl --fail-with-body "$OPENCRAWL_URL/api/internal/cost-rates?limit=100&offset=0" \
  -H "Authorization: Bearer $OPENCRAWL_OPERATOR_TOKEN"
```

The import response includes the immutable `revision`. Listing supports an optional
`provider` filter, a limit of 1–200 and an offset up to 100,000. Request bodies are
limited to 8 KB. No API edits or deletes a revision.

`POST /api/internal/runs/{run_id}/economics/value` previews matching historical
unpriced events by default. Supply the chosen `rate_revision`, optional boolean
`dry_run` (default true) and integer `limit` (default 100, maximum 500). Review
`eligible_count` and exact `estimated_subtotal_usd` against the measured economics
report. Commit using the same body with `dry_run: false`.

```sh
# valuation-preview.json contains {"rate_revision":"<imported revision>"}.
curl --fail-with-body "$OPENCRAWL_URL/api/internal/runs/$RUN_ID/economics/value" \
  -H "Authorization: Bearer $OPENCRAWL_OPERATOR_TOKEN" \
  -H 'Content-Type: application/json' --data-binary @valuation-preview.json

# valuation-commit.json additionally contains "dry_run": false.
curl --fail-with-body "$OPENCRAWL_URL/api/internal/runs/$RUN_ID/economics/value" \
  -H "Authorization: Bearer $OPENCRAWL_OPERATOR_TOKEN" \
  -H 'Content-Type: application/json' --data-binary @valuation-commit.json
```

A confirmed batch locks eligible rows and updates only unpriced events. Retrying or
concurrent confirmation cannot reprice a pinned event. Repeat a bounded batch if
more events remain. The returned subtotal describes that batch, not complete COGS.

## Coverage and unknowns

`GET /api/internal/runs/{run_id}/economics` adds per-dimension `coverage`:

- Provider units report measured records, missing quantities, unclassified legacy
  records and providers/operations observed without reported units. Invalid
  negative, fractional, nonfinite, boolean or out-of-range quantities stay unknown.
  Reported zero is retained; a dollar valuation still requires a sourced rate.
- Native Playwright captures wall-clock `elapsed_ms`, including failed attempts.
  Settlement stores the accumulated measurement transactionally in
  `ih_run_cost_measurements`. This is partial browser coverage, with unknown USD
  value; it does not measure CPU, billed browser minutes or external backends.
- Model, compute, storage, delivery and proxy remain `not_instrumented`.

`unpriced_reason_counts` distinguishes `missing_rate`, `outside_validity_window`
and `valuation_required`. A known subtotal can coexist with missing costs.
`provider_cost_total_usd` is null if recorded units/observed provider operations
have gaps or any event is unpriced. `provider_unit_valuation_state: valued` only
means the recorded provider units have valuations. It is not an invoice or
per-attempt completeness claim. Overall `cost_state` remains `unknown`, and
`total_cost_usd` and canonical run internal cost fields remain null.

## Migration, compatibility and verification

Schema installation is additive and idempotent. Existing provider rows are
classified where their attempt/ref or credit quantity gives evidence. Other legacy
rows remain unclassified. Existing events receive their source operation without
changing measurement or valuation. Existing terminal browser counters are
backfilled once. Triggers capture new events inside the settlement transaction;
rollback removes both cost facts and measurements.

Previous application revisions can ignore the additional columns/tables. For an
application rollback that must stop new rate pinning and runtime capture, pause
writers, roll back the application, then disable the two producer triggers
`ih_cost_event_rate_pin` and `ih_z_run_runtime_cost_measurements`. Preserve the
recorded facts and revisions. Reinstalling this schema recreates its triggers.
Correct pinned valuation disputes require a future adjustment/reconciliation
contract; this API deliberately cannot overwrite the audit trail.

PostgreSQL tests cover duplicate/concurrent imports, concurrent valuation,
precision, bounded confirmation, validity boundaries, unknown quantities,
immutability, additive reinstall, transaction rollback and operator authorization.
Browser meter tests cover success and failure. Production authenticated operator
execution and actual invoice reconciliation still require authorized credentials
and sourced rates. Margin, spend-policy enforcement and cost-aware routing remain
subsequent work.
