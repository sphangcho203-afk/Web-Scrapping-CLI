# OpenCrawl continuation — 1 October 2026

## Scope and baseline

Repository: `sphangcho203-afk/Web-Scrapping-CLI`. Refreshed #45 at `dbc61de` and
#47 initially at `8aa6450`. While work was underway, #47 advanced to `34f300d`,
including reconciliation with #45 and a first run-receipt slice. Continued from
that upstream implementation rather than publishing a duplicate. No user changes
were overwritten and no draft was promoted to production.

## Research and current-state audit

The supplied market research identifies operational traceability and cost truth as
prerequisites for recurring data products. Repository evidence supported that
order: capabilities already shared wallet request IDs but had different durable
execution models; receipts reflected billing rather than execution. Provider
reported units existed, but were not durable cost facts. No independent customer
research or demand measurement is claimed in this tranche.

## Implemented behavior and architecture

Wave 1 extension: canonical request identity, normalized execution alongside billing,
transactional source/output/provider-attempt bridges, retries/warnings/source counts,
duration, compatible specialized IDs, cancellation facade and a responsive Runs page.
An integration test exposed a PostgreSQL type-inference error in target-specific
extraction claims; the nullable parameter now has an explicit text type.

Economics foundation: measured provider unit facts, transactional/idempotent capture,
precision-preserving internal reads, explicit unknown valuations and coverage.
Existing reservations, leases, datasets and settlement remain the authorities.

## Database, API, economics and UX

Additive receipt fields and sanitized events extend `ih_runs` / `ih_run_events`.
`ih_cost_events` references measured provider usage and canonical runs; dollars are
nullable numeric/generated amounts, separate from wallet credits.

Read `/api/runs` and `/api/runs/{id}` with a session or scoped key. Cancel through
`POST /api/runs/{id}/cancel` with execute scope. Operators read
`/api/internal/runs/{id}/economics` using the existing service-token/OIDC boundary.
Customer run reads exclude private provider data and internal valuations.

`/dashboard/runs` exposes history, polling, paged events, output and cancellation.
Existing Usage and specialized views remain compatible. A started provider
extraction has no cancellation promise. No capability pricing changed.

## Documentation and verification

Contracts and executable curl examples: `CANONICAL_RUNS.md` and
`OPERATOR_COST_EVENTS.md`; the product docs include a Runs guide.
`MAXIMUM_VALUE_DIRECTIVE_STATUS.md` records implementation versus verification.

Wave 1 local full suite: 825 passing tests; final run-envelope set: 9 passing tests.
Wave 1 draft PR #48 at `8541b56` has green exact-head Python 3.11/3.12/3.13,
PostgreSQL, Chromium and Vercel checks. A deployed preview read of `/api/runs`
returned the expected unauthorized/sign-in-required response. This is only an auth
gate smoke check, not authenticated provider execution evidence.

Economics verification includes measured/unknown/zero units, duplicate settlement,
rollback, import and operator authorization, followed by the integrated local suite (829 passed) and
exact-head CI. See the dependent PR's check results for its published head.

## Limitations and next tranche

Production authenticated quote/confirm/provider execution/polling/export/settlement,
monitor baseline/change behavior and controlled signed delivery are not verified.
No promotion or branch pruning occurred. Detailed checkpoint events, quote-only
identity and populated workflow/live Dataset parentage remain subsequent work.
Unbilled HTTP health probes remain monitor history.

Reconciled provider invoices, full infrastructure measurement, spend-policy controls,
margin dashboards and cost-aware routing remain. Overall run COGS stays unknown;
wallet burn and reported provider credits are not converted to imaginary dollars.
Next work should extend measurement and economics guardrails before recurring
workflows multiply unknown costs.

## Sourced rate and coverage continuation

The dependent `codex/versioned-provider-rates-20261001` tranche adds immutable
content-addressed provider-credit rates, sourced/as-of validity, pinned decimal
estimates and an operator-only historical valuation flow that previews by default.
Existing valuations are never repriced. Unknown quantity/provider/operation gaps
block provider totals; unpriced reasons expose missing and stale rate contracts.
Native Playwright wall-clock measurement includes failed attempts and persists
inside settlement. Customer credit settlement and quote conversion do not change.

`PROVIDER_COST_RATES.md` records architecture, API examples, additive migration and
rollback compatibility. PostgreSQL coverage includes concurrency, exact precision,
validity boundaries, immutability, malformed quantities, operator authorization,
bounded preview/confirmation and schema reinstall. The integrated local suite
passed 858 tests with PostgreSQL and Chromium; Ruff, compile and whitespace checks
also passed. Published exact-head CI/preview evidence belongs in this tranche's PR.

No actual rate is seeded without its source. These estimates do not establish
reconciled invoice cost, full browser/compute/model/infrastructure coverage or
positive margin. Production authenticated operator execution remains unverified.

## Account/key spend-policy continuation

Refreshed the unchanged draft stack through #50 at `5826e82` and continued on
`codex/spend-policies-20261001`. Additive owner/key policy rows enforce optional
per-run/day/month caps at wallet reservation, using posted charges plus active
holds. No cap is imposed by default. Saved versions prevent lost updates; accepted
requests preserve applied policy provenance and original billing. Quotes remain
price-compatible and eligibility is checked at admission.

The `/dashboard/spending` page manages account and owned key limits, with USD
display, usage/headroom, explicit saves and conflict/retry states. API keys cannot
raise limits; foreign keys cannot be inspected. Monitor scheduler denial records
blocked history without a charge or job and recovers when limits permit a later
check. `SPEND_POLICIES.md` documents architecture, admission-period UTC semantics,
owned APIs, additive migration, rollback and remaining scope. Exact-head
verification evidence belongs in the dependent PR; production authenticated
execution remains unverified.

Final integrated local verification passed 885 tests with PostgreSQL 16 and
Chromium. Ruff, Python compile, JavaScript syntax and whitespace checks passed.
The initial full-suite concurrency-order regression was corrected without
changing the existing test or its contract; the final run includes that check.
