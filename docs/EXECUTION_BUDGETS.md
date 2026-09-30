# Execution cost review and spending limits

Playground follows input → review cost → confirm → reserve → execute → settle → inspect results. Reviewing is authenticated and read-only: it creates no job, reservation or usage event. Confirmation uses a fresh server quote and an optional user spending limit. Users can adjust the limit or workload before any collection begins.

## Components and responsibilities

| User action / system step | Owner | Contract |
| --- | --- | --- |
| Review immediate work | POST /api/playground/quote | Same normalized inputs and execution identity as /run; no-store |
| Review background work | POST /api/crawl-runs/quote | Same normalized crawl inputs and ownership checks as job creation; no-store |
| Confirm | Playground | Explicit second action; changed controls invalidate review |
| Enforce limit | ControlStore.reserve_tool_call | Compare current maximum reservation to the cap before database reservation or execution |
| Bind reviewed price | quote_revision | SHA-256 of owner, tool, plan, normalized execution inputs and quoted pricing |
| Hold funds | Existing wallet transaction | Reserve only with sufficient available funds; never overspend concurrent wallet balance |
| Execute | Playground or fenced background worker | Bounded input, time, page and provider budgets remain enforced |
| Settle | Canonical usage and credit ledgers | Charge at the reservation's stored multiplier; release unused funds; settlement is terminal/idempotent |
| Explain outcome | Results, background progress and Usage | Charges, reserved/released funds, pending outcomes, errors and saved results remain traceable |

Both quote endpoints return a quote containing credits, maximum_charge_credits, quote_revision, wallet_units_per_usd, available_credits and affordable. Available funds are informational at review time: execution locks and checks the wallet again. A quote is a maximum reservation, not a prediction of actual work or a guarantee that a provider is available. No provider execution occurs during review. URL validation may resolve the public target.

## API controls

Execution accepts optional max_charge_credits, an integer from 0 to 1,000,000,000 in internal wallet units. It is a ceiling for the whole reservation, not an instruction to perform partial unfunded work. A smaller ceiling rejects the request with spend_limit_exceeded (409). Booleans, floats, strings and null are invalid. A provided quote_revision must still match; changed price or inputs return quote_changed (409), requiring a fresh review. Direct clients can omit these controls for compatibility; the console always confirms with both.

Quoted inputs use the same normalizer as execution. Authorization is evaluated again on confirmation. Quotes are not transferable: revisions include the account identity. A quote does not reserve capacity, bypass revoked keys or promise execution at a stale price. No expiry token is needed; the revision is compared with the current policy and inputs. A policy/input change invalidates it immediately.

The USD field converts using the quoted wallet scale. One internal unit is the smallest increment. An empty field uses the reviewed maximum. Confirmation sends the exact integer cap and revision. Requests edited while a quote is loading discard that response. Failed reviews cannot start work. A new review is required for a retry.

Background idempotency includes the explicit budget inputs. Retrying the identical confirmed request returns its original owned job and reservation, even if later policy changed. Changing the inputs under the same Idempotency-Key remains a conflict. Existing clients without these fields preserve their old normalized inputs.

## Paid recovery and operator economics

New Playground requests default to paid_recovery: false. Native search and evidence work follow the existing bounded completion policy. The checkbox authorizes paid search/evidence recovery and shows its maximum before confirmation. It does not enable browser, PDF or schema extraction work. Basic paid search is discovery-only, at most ten results, without scrapeOptions. Evidence recovery makes at most three basic single-page requests, with parsers: [] to exclude PDF page fan-out.

The recovery route uses the same internal rate as the main tool router: 250 raw units per external basic work unit, then the configured wallet multiplier. Search reserves two basic work units for the bounded discovery call; evidence reserves at most three. Unused branches release their headroom. A successful upstream response uses reported credits where available; if absent, it records and charges the disclosed basic-operation policy units (two for search, one per successful scrape request). Failed calls without reported cost do not create a guessed charge. A returned paid page can be charged even if it contains an error or does not improve evidence; the returned upstream work and recovery outcome are separate.

Provider reports, policy units and results remain in measured usage for reconciliation. Charges cannot exceed the reservation/cap. Unexpected external overages are absorbed within this ceiling; this policy does not guarantee profit. Native compute, provider subscription costs, payment fees, promotional credits, taxes and unrecovered in-flight requests need operator cost reconciliation. Avoid changing customer prices invisibly to cover those costs; update policy, issue fresh quotes and preserve accepted reservation pricing.

Basis checked 2026-09-30: [Firecrawl Search cost and bounded options](https://docs.firecrawl.dev/features/search#cost-implications) and [provider charge behavior](https://www.firecrawl.dev/). Upstream terms can change; the mapping is an OpenCrawl pricing policy rather than a promise of the provider's invoice amount. Older direct pricing calls without the explicit recovery field retain their previous settlement mapping.

## Settlement and failure behavior

| Outcome | Accounting / user behavior |
| --- | --- |
| Invalid inputs, insufficient cap, changed quote | No execution reservation or job created |
| Wallet changed after review | Execution fails before work if the current wallet cannot cover the maximum |
| Native crawl with no successful output | Completion charge released; diagnostics can be saved |
| Queued cancellation | Full reservation released |
| Running cancellation / partial successful capture | Captured work can be charged within the original ceiling |
| Stop waiting for an immediate request | Browser stops waiting; server may finish and charge; inspect Runs |
| Retry after a lost background response | Same confirmed inputs and key return the original reservation |
| Background process/pricing configuration change | Worker reads stored raw ceiling; settlement uses stored multiplier |
| Repeated settlement or late worker | Existing terminal settlement is retained |
| Immediate dataset persistence failure | Result remains in response with an explicit copy-before-leaving warning; execution may still be charged |
| Background persistence/settlement failure | Atomic transaction rolls back and the fenced job remains recoverable |

Reserved usage events are pending, alongside accepted events, and are excluded from completed-request success/failure rates. Background detail distinguishes held funds, final charge and released reservation. These analytics represent posted usage charges, not historical wallet balances.

## Verification

CI tests cover invalid/insufficient caps before database access, revision binding, bounded paid headroom, disabled paid routes, quote normalization/private caching, PostgreSQL denial without ledger/job creation, stable pricing across process changes and idempotent completion. Chromium covers separate review/confirmation, changed-input requoting, insufficient caps and responsive layout. Existing crawler, wallet, monitor, dataset, webhook and usage checks remain required.

Production promotion still requires an authenticated deployed review → confirm → protected worker tick → saved results → reconciled wallet/Usage flow, plus cancel and duplicate-submission checks. No live account or external invoice reconciliation is claimed by CI.
