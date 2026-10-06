# Account and API-key spending limits

## Decision and behavior

A caller's per-request maximum cannot cap cumulative work from a schedule or
integration. Add account and API-key credit policies at the shared
`ControlStore.reserve_tool_call` boundary. They apply to new wallet reservations
from immediate tools, durable crawl/extract work and content monitors. An API-key
request must satisfy both its key policy and the account policy. A session request
still satisfies the account policy.

Policies have optional per-run, daily and monthly limits in integer wallet credits.
`null` means no limit; zero prevents new paid work. Ordinary rate, concurrency and
wallet checks still apply. Limits never grant funds, modify prices or convert
provider costs into customer charges. Unbilled tools consume no policy headroom.
No default limit is imposed on existing accounts or keys.

The signed-in owner manages limits at `/dashboard/spending`. The page displays USD
using the server's wallet conversion and sends integer credits, including the
smallest unit. It shows charged/reserved usage, remaining headroom and the next UTC
reset. Select Whole account or an owned key. Blank fields clear limits; saves are
explicit. Failed loads cannot display an editable policy. Conflicting saves keep
edits visible and require a reload.

## Admission, settlement and time semantics

A configured period counts **posted usage charges plus active reservations**.
Equality with the cap is allowed; a larger maximum is rejected before wallet
mutation, usage insertion, job creation or execution. Settlement replaces the
hold with its actual posted charge, releasing unused headroom. Cancellation and
abandoned-request release restore headroom. Settlement remains terminal and
idempotent, and cannot charge more than its accepted reservation.

Periods are UTC calendar days and months. Work is attributed to the period of its
reservation admission, including work finishing after a reset. A prior-day hold
still counts in the same month, but not in the new day's admission allowance.
The read snapshot's interval is half-open `[period_start, as_of)`; future rows are
excluded. This is reservation-period credit accounting, not a rolling window,
invoice expense or cash-revenue calculation. Wallet grants/top-ups and financial
refunds are outside these usage caps.

The account wallet row serializes admission and policy saves. The checker reads
committed charges/holds under that lock and records the admission timestamp inside
the transaction, after any lock wait. Every admitted paid request stores the
applicable policy scopes, versions and limits in its usage `metadata.budget`.
Policy saves take an owner FK-compatible lock before the wallet, matching durable
creation's owner-before-wallet order. Snapshot reads use a repeatable-read,
read-only transaction. No separate quota counters can drift from settlement.

Lowering a limit below current commitments is allowed. It blocks new paid
admissions but does not revoke or reprice accepted work. Identical durable retries
return the original job without reserving again. Existing price/input quote
revisions remain unchanged: policy eligibility and available headroom are checked
at admission, so a previously affordable quote can subsequently be denied.

Historical charges and valid active reservations count immediately when a policy
is enabled. An active legacy reservation with an unreadable credit quantity makes
its configured period unavailable; paid admission fails closed with
`spend_usage_unavailable`. The report marks its remaining headroom unknown. It does
not manufacture a zero hold. Existing stale-release protections retain active
specialized jobs.

## Owned API contract

Management requires the existing signed-in account session. An execution API key
cannot raise its own or the account's limits. Foreign keys return 404. All responses
use `Cache-Control: no-store`; the report contains no provider contracts or USD
provider valuations.

| Route | Method | Behavior |
| --- | --- | --- |
| `/api/spend-policy` | GET | Current account policy and period usage |
| `/api/spend-policy` | PUT | Replace all three account limits |
| `/api/api-keys/{key_id}/spend-policy` | GET | Current owned key policy and usage |
| `/api/api-keys/{key_id}/spend-policy` | PUT | Replace all three owned key limits |

PUT requires exactly `single_run_limit_credits`, `daily_limit_credits`,
`monthly_limit_credits` and `expected_version`. Each limit is null or an integer
from 0 to 1,000,000,000. Boolean, fractional, negative, string and unexpected fields
are rejected with 422. Request bodies are bounded at 4 KB. Missing policies return
version 0 with all limits null. Every successful save increments the version;
a stale `expected_version` returns `spend_policy_changed` (409). Reload before
retrying a save whose response was lost.

```sh
# owner-session.cookies contains the existing authorized account session.
curl --fail-with-body "$OPENCRAWL_URL/api/spend-policy" \
  -b owner-session.cookies

# policy.json uses the version returned by GET and supplies all three limits.
curl --fail-with-body "$OPENCRAWL_URL/api/spend-policy" \
  -X PUT -b owner-session.cookies -H 'Content-Type: application/json' \
  --data-binary @policy.json
```

GET/PUT return `policy`, `usage`, `enforcement: hard_stop`, `unit: wallet_credit`
and `wallet_units_per_usd`. Each period reports charged, reserved and committed
credits, unknown reservation count and nullable remaining credits. A null remaining
value means either no configured limit or an explicitly marked unknown hold.

Admission errors use `spend_policy_exceeded` (409) and explain the applicable
account/key limit, commitments and required maximum. The existing request-specific
`max_charge_credits`, quote binding and wallet errors remain compatible. Content
monitor scheduler denial records a blocked history entry with zero charge; a
future scheduled check can recover after the owner changes limits.

## Migration and verification

`ih_spend_policies` is additive, keyed by owner/scope and linked to owned API keys.
Schema reinstall preserves saved policies. No historical usage, wallet or
specialized job state is rewritten. Disabling all fields retains the version for
conflict detection. Rolling back to an application without this checker stops
policy enforcement; preserve the table and communicate that behavioral change.
This tranche adds hard stops, with no warn-only or threshold-notification contract.

PostgreSQL tests exercise simultaneous admissions and policy writes, partial and
duplicate settlement, cancellation, abandoned release, accepted-job retries,
rollback, schema reinstall, ownership, UTC/year boundaries, malformed legacy
holds, metadata provenance and monitor block/recovery. Chromium tests exercise
account/key scope, minimum-unit USD conversion, zero/blank limits, stale-save
errors, reload/retry, unknown headroom and mobile layout. Production authenticated
policy saves and real provider/worker enforcement remain unverified until tested
on an authorized deployed account.

Organization/workspace policies, notifications, rolling windows, operator margin
floors and cost-aware routing remain subsequent work. Complete provider COGS and
margin remain unknown; these credit caps do not establish profitable execution.
