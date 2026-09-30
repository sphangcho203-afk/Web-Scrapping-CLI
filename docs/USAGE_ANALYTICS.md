# Usage analytics

Overview and Usage render responsive SVG charts from the authenticated canonical usage ledger. Requests and posted credit charges use bars; average latency and success rate use lines with gaps for unavailable measurements. Charts have labeled axes, a keyboard/touch bucket selector, an exact table and CSV export. The window and metric are shareable URL parameters. Recent run inspection remains available.

## Accounting contract

`GET /api/usage/intelligence?window=24h|7d|30d|90d&recent_limit=1..50` is user-scoped and returns `Cache-Control: no-store`. One server timestamp defines the half-open interval `[start, end)`. Ledger totals, series, breakdowns and recent requests use a single PostgreSQL repeatable-read snapshot. Future events are excluded. The account wallet is a separate live account read, not a historical balance chart.

| Measure | Meaning |
| --- | --- |
| Requests | All ledger events created inside the selected interval |
| Credits | Sum of recorded `credits_charged`; excludes top-ups, rewards and outstanding reservations |
| Success | `ok` events divided by completed events; `accepted` events are pending and excluded |
| Failures | Every outcome other than `ok` and `accepted` |
| Latency | Average and p95 of recorded latency measurements; sample count is returned; missing measurements remain null |

Buckets align to UTC hours for 24h and UTC days for longer windows. Quiet buckets contain zero request/credit counts and null latency/success. Rolling ranges usually cross 25 hourly or 8/31/91 daily buckets. The first and last can be partial: explicit `bucket_start`, `bucket_end` and `partial` fields identify their actual coverage. Bucket counts and charges sum to the corresponding totals. A request stays in its creation-time bucket when its outcome is updated.

Tool and status breakdowns retain the ten largest groups plus an explicit remainder, so their displayed shares account for all requests. Provider breakdowns retain the ten largest providers. Recent ledger rows are bounded independently of full-window totals. Average bucket latency is not an unweighted estimate of the window average.

## Interaction and refresh

Metric selection redraws the same snapshot without refetching. Window selection and Refresh data fetch a fresh snapshot; there is no automatic polling. The updated timestamp is visible. A failed refresh preserves the previous chart and marks it stale. An initial fetch failure presents a retry action, not invented zero totals. Requests use generation guards to prevent older responses replacing newer selections.

SVG geometry is measured on resize, with at most 91 buckets and one chart instance per page. Native range controls provide arrow/Home/End keyboard access, point selection works by pointer or tap, and the table exposes exact values without relying on color or hover. CSV exports all buckets, including partial edges and null measurements.

## Verification and remaining scope

Pure tests cover UTC bucket boundaries, quiet periods and pending-only success semantics. PostgreSQL CI tests cover ownership, time bounds, totals reconciliation, empty ledgers and operation remainders. Chromium tests exercise metric/window changes, keyboard inspection, CSV, failed-refresh recovery and 320/390/1366px layouts. The endpoint contract checks authorization, parameter bounds and private caching.

This tranche adds read-only analytics. Per-key filtering, comparison periods, historic wallet balances and forecasting remain separate work. Authenticated deployed-account verification is still required before production promotion.
