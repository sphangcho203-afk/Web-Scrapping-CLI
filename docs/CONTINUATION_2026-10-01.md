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

Provider invoice rates, full infrastructure measurement, spend-policy controls,
margin dashboards and cost-aware routing remain. Overall run COGS stays unknown;
wallet burn and reported provider credits are not converted to imaginary dollars.
Next work should capture versioned valuation sources and measurement coverage,
then add economics guardrails before recurring workflows multiply unknown costs.
