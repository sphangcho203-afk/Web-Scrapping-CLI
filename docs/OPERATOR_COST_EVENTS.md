# Operator cost-event foundation

This tranche captures measurable provider usage before adding invoice rates or
claiming profitability. It is separate from customer wallet accounting.

`ih_cost_events` records provider-reported credit units already persisted in
`ih_provider_usage`. A source event ID is the unique cost-event identity. The
provider-usage trigger executes inside settlement's transaction, so rollback and
idempotent settlement preserve one authoritative event. Historical reported units
are backfilled idempotently. Unknown quantities are not invented; reported zero
units are retained as a fact, without inferring a free dollar cost.

Fields include canonical run ID, provider, cost type, quantity, unit, optional
unit cost, generated dollar total, measurement source, valuation source,
estimation flag and timestamp. Monetary fields use PostgreSQL `numeric`; internal
JSON responses serialize decimals as strings to preserve precision. A price cannot
be stored without its valuation source. No invoice loader or rate-edit endpoint is
implemented in this foundation.

## Internal read interface

`GET /api/internal/runs/{run_id}/economics?limit=100&offset=0` returns measured
facts and an all-events summary. It uses the existing CRON_SECRET / authorized
GitHub OIDC service boundary, as do provider reliability diagnostics. Sessions and
customer API keys do not authorize this endpoint. Responses are private and
`no-store`; provider names and valuations stay out of the customer Runs API.

```sh
curl "$OPENCRAWL_URL/api/internal/runs/$RUN_ID/economics" \
  -H "Authorization: Bearer $OPENCRAWL_OPERATOR_TOKEN"
```

`known_cost_subtotal_usd` stays null when nothing is priced.
`provider_cost_total_usd` stays null when any recorded quantity is unpriced.
`provider_unit_valuation_state` distinguishes an entirely valued recorded unit set
from missing valuations. Overall `cost_state` remains `unknown`, coverage is
`provider_units_only`, and total run COGS remains null: compute, storage, bandwidth,
proxy/model/browser costs and invoice reconciliation have not been instrumented.
The canonical run's internal dollar cost fields remain unfilled. Customer wallet
burn is never silently treated as provider dollars.

## Evidence and next work

PostgreSQL tests cover measured units, zero and unknown quantities, duplicate
settlement, rollback, historical import and operator authorization. Existing run,
wallet and dataset tests verify integration. Production operator reads and actual
provider invoice valuations remain unverified.

Next: ingest versioned rates with an explicit source/as-of date, record browser,
model and infrastructure units, track measurement coverage, and then build margin
analytics and routing safeguards. A billed successful run is not yet evidence of
positive margin.
