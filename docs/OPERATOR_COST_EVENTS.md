# Operator cost events

`ih_cost_events` records provider-reported credit units already persisted in
`ih_provider_usage`, separately from customer wallet accounting. A source event ID
is the unique cost-event identity. Capture runs inside settlement's transaction;
rollback and idempotent settlement preserve one authoritative event. Historical
reported units are backfilled idempotently. Invalid or missing quantities stay
unknown. Reported zero remains a measurement without implying a free dollar cost.

Fields include canonical run ID, provider, operation, cost type, quantity, unit,
optional unit cost, generated dollar total, measurement source, valuation source,
rate revision, estimation flag and timestamp. Monetary fields use PostgreSQL
`numeric`; internal JSON serializes decimals as strings. Measurement facts and
pinned valuations are immutable. See [PROVIDER_COST_RATES.md](PROVIDER_COST_RATES.md)
for sourced imports, validity, historical valuation and migration contracts.

## Internal read interface

`GET /api/internal/runs/{run_id}/economics?limit=100&offset=0` returns paged measured
facts, an all-events summary and per-dimension measurement coverage. It uses the
existing CRON_SECRET / authorized GitHub OIDC service boundary. Customer sessions
and API keys cannot authorize it. Responses use `no-store`; provider names and
valuations stay out of the customer Runs API.

```sh
curl "$OPENCRAWL_URL/api/internal/runs/$RUN_ID/economics" \
  -H "Authorization: Bearer $OPENCRAWL_OPERATOR_TOKEN"
```

`known_cost_subtotal_usd` stays null when nothing is priced.
`provider_cost_total_usd` stays null when quantities/observed provider operations
have gaps or any recorded unit is unpriced. `provider_unit_valuation_state`
distinguishes valued recorded units from missing measurements or valuations.
`unpriced_reason_counts` exposes missing, out-of-window and unreviewed rates.

Overall `cost_state` remains `unknown`, summary coverage is `provider_units_only`
and total run COGS remains null. Native Playwright wall-clock duration is partially
measured, with unknown cost; model, compute, storage, delivery and proxy dimensions
remain uninstrumented. The canonical run's internal dollar cost fields remain
unfilled. Wallet burn is never silently treated as provider dollars.

## Evidence and remaining work

PostgreSQL tests cover measured/zero/unknown/invalid units, duplicate settlement,
rollback, historical import, sourced rate precision/concurrency/immutability and
operator authorization. The real customer run store excludes private valuations.
Native browser meter tests cover successful and failed attempts. See the published
PR's exact-head checks for CI evidence. Production operator execution and actual
provider invoice reconciliation remain unverified.

Next: instrument remaining infrastructure/model units, reconcile invoices and
adjustments, then build margin analytics, spend policies and routing safeguards.
A billed successful run is not yet evidence of positive margin.
