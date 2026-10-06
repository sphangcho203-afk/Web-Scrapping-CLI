# Provider-reported dollar observations

## Contract and source

Exa's existing `search` and `contents` adapters expose the response field
`costDollars.total`. The application now preserves that numeric token as an exact
decimal observation before the ordinary response decoder or rounded wallet-pricing
counter can lose precision. No amount is inferred from wallet credits or guessed
from a price list. Other provider integrations have no dollar-report producer yet.

Supported totals are JSON numbers, nonnegative, below USD 1,000,000 and exactly
representable with at most twelve decimal places. Reported zero is retained.
Numeric strings, booleans, negative/nonfinite values, excessive precision and
out-of-range values are invalid evidence. Missing/null totals are `not_reported`;
invalid totals or cost containers are `invalid_reported_total`. Both store a null
amount, not zero. Raw malformed values are never retained in the private report.
Nonfinite public cost fields become null so they cannot break JSON serialization.

These are provider response statements, with `reconciliation_state: unreconciled`.
They do not establish actual invoice expense, taxes, discounts, refunds or complete
COGS. `observed_at` is the application's response-capture time, not an invoice
date. The source marker is `exa_response_cost_dollars_total`. Upstream reference:
[Exa Search API](https://docs.exa.ai/reference/search).

## Persistence and recovery

Each response gets a server-generated `pcost_...` observation ID. The execution
meter stores its operation, source, state, normalized decimal string and capture
time. Worker checkpoints retain those fields and IDs; resuming the meter copies
them without changing the checkpoint. Concurrent responses have distinct IDs.
Existing empty meter snapshots keep their previous shape.

Settlement inserts observations into `ih_provider_dollar_reports` in the same
transaction as provider-unit facts, wallet changes and the usage receipt. A save,
charge-validation or transaction failure rolls the observations back. Retrying a
settlement/checkpoint with the same ID and evidence records one observation.
Reusing an ID with conflicting evidence fails settlement atomically. Observation
identity is scoped to the canonical run.

An overall failed run can still retain a real observed provider amount, including
when the customer charge is zero. Duplicate or late settlement follows the
existing terminal receipt contract: it cannot append or rewrite evidence after
closure. More general late-cost adjustments require a future reconciliation
contract. Database guards prevent observation updates; no operator write API can
change an amount or attach a rate revision.

Capture currently covers successful HTTP responses containing parseable JSON
objects. Failed HTTP responses, transport failures and missing checkpoints can
leave unobserved cost. A crash before checkpoint or settlement can lose in-memory
reports. Persisted provider attempts/call counts expose the gaps they can prove;
they do not reconstruct all past traffic. Overall coverage remains partial.
Legacy `exa_cost_microusd` counters and raw saved outputs are not backfilled into
exact reports. The existing finite legacy counter and customer pricing calculation
remain compatible; this tranche changes no quote, reservation or rate import.

## Operator read interface

Read the existing service-token / authorized GitHub OIDC endpoint:

```sh
curl --fail-with-body "$OPENCRAWL_URL/api/internal/runs/$RUN_ID/economics?limit=100&offset=0" \
  -H "Authorization: Bearer $OPENCRAWL_OPERATOR_TOKEN"
```

The response adds `provider_dollar_reports`, paged by capture time and ID, and
`coverage.provider_reported_dollars`. Existing `limit`/`offset` bounds apply
independently to provider-credit events and dollar reports. Aggregates cover all
observations regardless of pagination. Decimal amounts are JSON strings and
responses use `no-store`. All reads use the report's single database snapshot.

| Field | Meaning |
| --- | --- |
| `report_count`, `reported_amount_count` | Recorded responses and responses with a valid amount |
| `not_reported_count`, `invalid_report_count` | Explicit missing and malformed response amounts |
| `observed_call_count` | Maximum of persisted Exa call counts, attempt records and response observations |
| `call_without_report_count` | Observed call count exceeding the number of captured responses |
| `operation_without_report_count` | Persisted Exa attempt operations without a response observation |
| `known_reported_subtotal_usd` | Exact sum of valid recorded amounts, null when none are valid |
| `overlapping_credit_operation_count` | Exa operations also represented by credit cost events |

Coverage declares supported `providers: ["exa"]`, `state: partial`,
`historical_coverage: not_reconstructed` and unreconciled status. Call counters are
an aggregate gap check, not a one-to-one mapping between reports and attempts.
A response lacking a total has a report but no known amount. No report/count does
not establish zero expense or absence of historical work.

`summary.known_reported_provider_subtotal_usd` mirrors the reported-dollar subtotal.
The existing `known_cost_subtotal_usd` retains provider-credit valuations, labeled
by `known_cost_subtotal_basis: provider_credit_valuations`. These subtotals are
separate observations and must not be added automatically: they can describe the
same expense, as the overlap count highlights. Rate revisions neither reprice nor
duplicate dollar reports. Provider-credit coverage keeps its existing unit-only
meaning. `total_cost_usd`, complete COGS, canonical internal costs and gross margin
remain unknown.

## Privacy, lifecycle and rollout

Dollar observations remain in private cost/checkpoint storage. Settlement removes
them from customer usage and wallet-ledger metadata before saving those receipts.
Canonical Runs and specialized job facades do not expose them. Existing raw Exa
tool responses retain their compatible response shape; this does not add private
observation IDs to those outputs. Queries, API keys, raw bodies and invalid values
are absent from the operator report.

The additive table follows canonical run/account deletion and retains observations
after dataset deletion. Schema reinstall preserves amounts and capture times;
there is no historical guessing or repricing. Roll back the application to stop
this producer while preserving the table and audit records. Older applications
ignore the added table and fields; they will not capture new reports. No producer
database trigger must be disabled.

Tests use actual PostgreSQL transactions and HTTP mock responses, including the
real Tool Mesh retry path. They cover exact precision, zero/invalid/missing amounts,
concurrent capture and settlement, checkpoint replay, conflict/charge rollback,
failed runs, pagination, immutable amounts, overlapping rates and customer/operator
privacy. No paid provider call is made in tests. Authenticated production capture
and provider invoice reconciliation remain unverified.
