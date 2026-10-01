## 1 October continuation update

Fresh main: `56ca429`. PR #45 remains draft at `dbc61de`; PR #47 was reconciled
with that parent in commit `2f84ecc`. Continue on the existing Structured Extract
branch; no new parallel implementation branch. Neither draft is promoted.

Wave 1 **PARTIAL**: additive canonical billing receipts/events, owned read APIs,
existing Usage inspector integration and migration regression coverage. See
`CANONICAL_RUNS.md` for semantics and remaining execution-event bridges.
Authenticated deployed verification remains **NOT VERIFIED**.

Local full suite before new receipt tests: 727 passed, 46 skipped, 15 failures
in existing provider tests due to unavailable DNS resolution. New API regression
passes. PostgreSQL regression is included in the dedicated CI database job;
local PostgreSQL startup is blocked by system-user creation restrictions.
Lint, compileall and JavaScript syntax pass. Exact-head CI must be checked after
publishing; this text does not claim green CI or production behavior.

# Maximum Value Directive — implementation status

Audit target: OpenCrawl maximum-value / market-demand / real-capability directive.
Repository baseline reviewed: `codex/saved-playground-datasets-20260930` at `6f3d99f64d5fe2f4c11860553cbea6d0c51872e2`.
This document distinguishes code that exists from production behavior that has actually been verified.

## Status legend

- **DONE** — implemented in code with a coherent execution path and meaningful automated coverage.
- **PARTIAL** — useful implementation exists, but one or more directive requirements are missing.
- **NOT DONE** — no complete OpenCrawl product path exists.
- **NOT VERIFIED** — code/tests exist, but the directive's production behavior gate has not been proven.

A feature is not called shipped here merely because a provider adapter or UI label exists.

## Executive status

The project already has a strong control-plane substrate:

- account/session/email verification/TOTP/security flows;
- scoped API keys and OAuth MCP authorization;
- Tool Mesh plus semantic capability registry;
- provider health/reliability, bounded retries and circuit behavior;
- universal tool availability with credit-metered hosted work;
- wallet reservations, settlement, USD top-ups, rewards and community reward codes;
- Playground search/research/crawl;
- durable background crawls with resumable frontiers and cancellation;
- owned datasets, JSON/JSONL/CSV export and signed dataset webhooks;
- content-change monitors;
- ledger-backed run/usage analytics with real SVG charts;
- connected applications, outbound remote MCP connections and capability discovery.

The directive is **not complete**. The highest-value missing product work is concentrated in turning already-registered capabilities into complete user workflows and filling the economic/automation gaps.

---

## Phase 0 — audit the real current product

**Status: PARTIAL**

### Done
- Current execution/storage path was traced in `VALUE_IMPLEMENTATION_AUDIT.md`.
- New crawl/dataset/monitor/budget work maps UI -> endpoint -> service -> DB -> usage -> output.
- Existing tests cover many auth, billing, MCP, wallet, provider and UI contracts from prior waves.

### Still missing
- One canonical whole-product map covering every directive flow from signup through admin/support.
- A single audited inventory of legacy routes, flags, migrations, duplicated implementations and unreachable UI.
- A production walkthrough of every listed user flow.

---

## Phase 1 — deep market / demand research

**Status: PARTIAL**

### Done
The current value audit references and compares patterns from Firecrawl, Apify, Zyte, Tavily, Browserless and public feature-request evidence.

### Still missing
The directive requested materially broader current research:
- Bright Data, Oxylabs, ScrapingBee, Crawlbase, Browserbase and additional SERP/search infrastructure;
- Reddit, Hacker News, developer forums and broader feature-request evidence;
- explicit demand evidence for business/leads, ecommerce, jobs, news, search/SERP and developer-data verticals;
- a complete capability matrix with market evidence, frequency, marginal cost, credit model, revenue potential and priority.

Current research is enough to justify datasets/crawls/monitors, but not enough to claim the directive's research phase complete.

---

## Phase 2 — product primitives

| Primitive | Status | What actually exists | Important gaps |
|---|---|---|---|
| Search | PARTIAL / strong | Playground search/research, Brave/native search, Firecrawl, You.com/Tavily/Exa/public indexes, semantic capabilities, citations/evidence paths | first-class Search surface and full domain/date/locale/language controls are inconsistent across routes; not every search path saves/quotes identically |
| Smart Scrape | PARTIAL | `web.fetch.page`, Firecrawl scrape, Apify fallback, native HTTP fetch, readable extraction | no first-class Smart Scrape workflow; routing currently prefers Firecrawl before native HTTP rather than explicitly choosing the cheapest sufficient path; result tabs/advanced overrides are incomplete |
| Structured Extract | PARTIAL | `web.extract.structured` semantic capability, Firecrawl bounded-agent route, public structured document extraction | no complete OpenCrawl schema/natural-language extraction workflow across URL(s), crawl results and saved datasets; no consistent schema-validation/provenance UI |
| Question / Highlights | PARTIAL / thin | Firecrawl scrape can request highlights/questions; research returns evidence | no product-level page/dataset Q&A primitive with grounded highlights and low-token mode |
| Crawl | PARTIAL / strong | synchronous crawl, durable background jobs, resumable frontier, robots/public-target policy, canonical redirects, sitemaps, cancellation, progress, datasets, accounting | no pause/resume user control, page graph, rendered crawl, extraction schema, multi-tick huge crawl, async search/research or remaining-cost forecast |
| Map | PARTIAL / newly productized | `web.map.site` now has `/api/site-map/quote` + `/api/site-map/run`, explicit review/confirmation, semantic routing, normalized/classified URL rows, saved datasets, console UI and docs; Firecrawl map + native link-map fallback remain behind the capability boundary | CI/deployed verification is still pending; native fallback only sees links on the fetched root page; no visual graph or select-subset -> crawl UX |
| Browser / Interact | PARTIAL | browser/sandbox backends, connected browser task capability, Firecrawl interact, Playwright-oriented infrastructure | no coherent first-class browser-task/session UI with reusable authorized profiles, session logs and expiry across providers |
| Monitor | PARTIAL | health/API/MCP-style monitors plus new owned content-change monitor using durable crawl jobs | content monitor is text/title only; no field/selector/search/product/stock/structured threshold models; actions are not a unified alert/delivery abstraction |
| Datasets | PARTIAL / strong | owned persistence, provenance-bearing output, search/filter/pagination, rename/delete, JSON/JSONL/CSV export, signed webhook event | no column-visibility controls, Markdown/XML/XLSX, rerun action, append-in-place monitor history, retention policy or broad destination delivery |
| Automations | NOT DONE as an OpenCrawl system | connected automation providers and semantic workflow execution exist | no native trigger -> action -> filter -> output model, schedule engine, step logs/cost/retry UI or workflow persistence |
| Tools / Recipes | PARTIAL | Tool Mesh + semantic capability registry with schemas/tags/candidates and health-aware execution | no outcome recipe entity/version/owner/docs URL/timeout class, no save-from-Playground recipe flow, no curated vertical template layer |
| Connect / Deliver | PARTIAL | signed dataset webhooks, connected apps, remote MCPs | no destination abstraction for S3/R2, Postgres, Supabase, Neon, Sheets, email, mapping/tests/logs per destination |
| Agent / MCP | PARTIAL / strong | inbound MCP, scoped keys, OAuth/PKCE, semantic registry, Tool Mesh, remote MCP import, connection UI/docs | production OAuth/client compatibility still needs live verification; capability metadata still lacks several directive fields and user-facing callable surfaces are uneven |

---

## Phase 3 — vertical high-value data products

**Status: MOSTLY NOT DONE**

OpenCrawl has broad public-data/research capabilities and a large gaming intelligence catalog, but the directive's commercial vertical packages are not implemented as coherent products.

Missing as first-class templates/products:
- business / lead discovery;
- ecommerce catalog + price/stock history;
- recurring jobs collection;
- news/topic timeline;
- SERP-specific product surface;
- docs/RAG pipeline recipes;
- researched real-estate/travel verticals.

Do not count generic tools or game-count inflation as completion of this phase.

---

## Phase 4 — unified execution engine

**Status: PARTIAL**

### Done
- canonical usage ledger with request IDs;
- reserved/settled wallet accounting;
- durable crawl-run entity with queued/running/completed/failed/cancelled behavior;
- provider attempts/reliability telemetry in the Tool Mesh;
- run inspection and usage history.

### Missing
There is no single durable `RUN` entity for **all** capability families containing one consistent:
- status model;
- input/output reference;
- provider/upstream cost;
- retry count;
- parent automation/crawl/monitor;
- durable step log;
- warnings;
- output size;
- partial/waiting semantics.

Immediate Tool Mesh, Playground, game, public-data and crawl paths still use related but distinct execution models.

---

## Phase 5 — wallet / credits / monetization

**Status: PARTIAL / strong**

### Done
- monthly/purchased/reserved balances;
- exact integer internal accounting;
- USD wallet display/top-up;
- universal tool access across plans;
- hosted credit-burn multiplier;
- reservation before execution;
- measured/idempotent settlement;
- unused reservation release;
- retry-aware reservation headroom;
- wallet ledger/history;
- reward points and community reward-code campaigns;
- server-side payment verification;
- Playground/background crawl quote revision and max-spend enforcement.

### Missing
- the same mandatory preflight quote/max-cost contract across all expensive capability families;
- internal gross provider/infrastructure cost ledger;
- margin by capability/provider;
- native compute/bandwidth/storage/payment-fee reconciliation;
- per-key/daily user spending budgets;
- historical wallet-balance analytics;
- explicit operator adjustment/refund UX covering every directive case.

Customer metering is substantially ahead of operator COGS accounting.

---

## Phase 6 — UX / information architecture

**Status: PARTIAL**

### Done
- operations-oriented console shell;
- Overview, Playground, Datasets, Background Crawls, Public Data, Games, Repositories, API Keys, Runs, Monitors, Connections, Wallet, Rewards, Billing, Settings;
- responsive navigation and mobile behavior;
- strong error/pending handling in many core forms;
- real ledger-backed usage charts.

### Missing
- first-class Search, Scrape, Extract and Map workflows;
- native Automations and Recipes surfaces;
- Playground dynamic selection of the entire callable capability registry;
- raw JSON mode for all supported capabilities;
- copy cURL / JS / Python for the current configured run;
- save-as-recipe/workflow;
- create-monitor-from-result where appropriate;
- format-specific result tabs only when available.

---

## Phase 7 — documentation

**Status: PARTIAL / strong for implemented tranches**

There are detailed docs for Tool Mesh, security/auth, providers, datasets, webhooks, durable crawls, monitors, usage analytics and execution budgets.

Missing:
- docs generated from / validated against the capability registry;
- complete first search/scrape/crawl/extract getting-started sequence;
- every endpoint documented with synchronized schemas/errors/pricing/limits;
- end-to-end guides for JS scraping, structured extraction, price monitoring, scheduled jobs and destination delivery;
- guaranteed executable examples for every surfaced capability.

---

## Phase 8 — provider abstraction

**Status: PARTIAL / strong**

Tool Mesh + semantic capabilities provide a useful generic provider boundary with:
- normalized descriptors;
- schemas;
- provider status;
- reliability state;
- capability candidates;
- health-aware/fallback routing;
- server-held credentials;
- normalized execution.

Remaining gap:
- routing does not yet explicitly optimize all Smart Scrape choices for cheapest-sufficient execution;
- provider COGS is not a first-class routing signal;
- not every capability family has a clean product-level adapter contract/destination abstraction.

---

## Phase 9 — reliability

**Status: PARTIAL / strong**

Implemented:
- typed/structured errors in core paths;
- request IDs;
- background run IDs;
- idempotency keys;
- timeouts;
- bounded replay-safe retries;
- concurrency limits;
- provider reliability/circuit state;
- health checks;
- webhook retries/signing;
- output-size limits;
- cancellation;
- partial crawl persistence;
- dedupe/frontier bounds;
- transactional settlement and dataset finalization.

Missing/incomplete:
- one universal dead-letter model;
- consistent retry/timeout classes exposed on every capability;
- pause semantics;
- complete end-to-end duplicate protection for every immediate route;
- production failure drills.

---

## Phase 10 — observability

**Status: PARTIAL**

### Done
- canonical usage ledger;
- requests/credits/success/failure/pending/latency time series;
- exact bucket table + CSV;
- recent run inspector;
- provider/system health primitives;
- request-level provider attempt telemetry.

### Missing
Business:
- active-user analytics;
- credits purchased/consumed as a joined business view;
- revenue;
- gross provider/infrastructure cost;
- margin by capability;
- conversion;
- repeat usage.

Product:
- successful-first-run funnel;
- MCP connection adoption;
- dataset/monitor/automation adoption reporting;
- tool/capability adoption dashboard.

Reliability:
- consolidated retry/provider/browser/crawl/webhook failure dashboards.

---

## Phase 11 — feedback / user-demand loop

**Status: NOT DONE**

No real first-class feedback capture/storage/triage system was found for:
- feature requests;
- failed-job feedback;
- desired sites;
- missing integrations;
- docs confusion;
- expensive/slow complaints;
- requested verticals;
- aggregate grouping by frequency/account value/capability/severity.

This remains a direct directive miss.

---

## Phase 12 — implementation waves

**Status: PARTIAL**

Delivered pieces span Wave 1 and Wave 2, but Wave 1 is not complete:
- Search: partial/strong
- Smart Scrape: partial
- Structured Extract: partial
- Crawl: partial/strong
- Map: backend-only partial
- unified Runs: partial
- Datasets: partial/strong
- accurate credits: strong
- Playground: partial
- API docs: partial

Wave 2 has content monitors and webhooks but lacks native automations, recipes and destination connectors.

Wave 3 has a strong MCP/capability substrate but lacks recipe ecosystem/vertical distribution/organization work.

---

## Phase 13 — testing

**Status: PARTIAL / strong for current branch**

Current PR validation covers large Python/PostgreSQL/Chromium suites and specifically tests crawl/dataset/monitor/budget/analytics behavior.

Still missing relative to the directive:
- one matrix proving every surfaced capability across happy/invalid/unauthorized/credits/timeout/error/retry/duplicate/cancel/empty/partial/large/mobile/desktop;
- integration connect/test/execute/revoke/expired-auth coverage for every connector;
- production E2E tests against real configured providers.

---

## Phase 14 — product quality gate

**Status: NOT PASSED for the draft branch**

The current branch is not production-verified.

CI and preview readiness do **not** establish:
- authenticated deployed quote -> confirm -> reserve -> real provider -> persist -> settle -> Usage;
- duplicate submission behavior in production;
- running cancellation behavior in production;
- baseline -> unchanged -> changed content-monitor sequence in production;
- external signed webhook receipt;
- external invoice reconciliation.

Under the directive's own definition, the new tranche is reviewable and well-tested, but not yet fully "shipped."

---

## Phase 15 — working style

**Status: PARTIAL**

Incremental commits, docs, tests and reviewable changes are present. The remaining process problem is branch sprawl: dozens of historical feature/hardening branches make canonical lineage harder to identify. New work should continue from one reviewed branch and old branches should be pruned after promotion.

---

## Phase 16 — final handoff

**Status: PARTIAL**

PR #45 is a useful release note, but a directive-complete handoff still needs:
1. broad market research findings;
2. whole-product current-state audit;
3. exact implemented feature inventory;
4. architecture;
5. database changes;
6. API changes;
7. credit model;
8. UX changes;
9. docs;
10. testing;
11. deployment;
12. real limitations;
13. next highest-value work.

---

# Next coherent implementation order

Do **not** add random provider cards.

1. **Finish verification of the new first-class Site Map workflow**
   - CI/build must pass on the exact branch head;
   - deployed authenticated quote -> confirm -> dataset -> Usage must be verified before promotion;
   - keep it marked unverified until that gate is proven.

2. **Smart Scrape workflow**
   - cheapest-sufficient native HTTP first;
   - escalate to rendered/provider path only when needed/explicit;
   - normalized Markdown/text/HTML/links/metadata;
   - screenshot/PDF only through capability routes that really support them;
   - quote, dataset and run trace.

3. **Structured Extract workflow**
   - schema or natural-language request;
   - URL(s), dataset and crawl inputs;
   - normalized JSON + validation/missing fields/provenance;
   - bounded model/provider budget.

4. **Unify immediate execution records**
   - one run contract across Playground, semantic capability, public data, games and background jobs;
   - parent linkage, retries, provider cost metadata and output references.

5. **Operator economics**
   - provider invoice/native compute/storage/payment-fee ledger;
   - capability/provider margin;
   - alerts for negative/unknown margin;
   - route/pricing decisions based on measured cost.

6. **Automations + destination abstraction**
   - only after the execution/run substrate above is consistent.

7. **Feedback/demand loop**
   - capture failed-run and missing-capability demand tied to actual account/capability context.

This order completes Wave 1 before creating broad Wave 2/3 surface area.


## Current continuation — Site Map tranche

Implemented after this audit on the same draft branch:

- first-class `POST /api/site-map/quote` and `POST /api/site-map/run`;
- semantic execution through `web.map.site`, not a new provider-specific product path;
- explicit cost review, quote revision and maximum-spend enforcement;
- normalized same-site URL rows with depth, parent and deterministic URL-path category;
- optional subdomains and sitemap behavior;
- saved map datasets using the existing 2 MB / 1000-row DatasetStore and JSON/JSONL/CSV export;
- semantic capability identity stored in the usage ledger for new capability executions;
- Site Map console route and navigation;
- in-product Site Map documentation plus curl/JavaScript/Python examples;
- targeted route, normalization, dataset and UI-contract tests.

This tranche is **implemented but not yet marked shipped**. CI and Vercel checks for the new head are currently required, followed by the directive's deployed production behavior gate.

## 1 October 2026 continuation — Wave 1 execution envelope

Fresh remote state: #45 remains draft at `dbc61de`; #47 now includes its parent
reconciliation plus the receipt slice at `34f300d`. This continuation extends that
same implementation on `codex/canonical-runs-20261001`, based on #47. No drafts were
merged to production or deleted.

**Implemented in code:** normalized execution status alongside compatible billing
status; transactional specialized state/output/provider-attempt bridges; bounded
source counts, retries, warnings, cancellation and duration; account-owned list/detail
and cancellation facade; responsive Runs history/inspector with event paging;
repository and product docs. See `CANONICAL_RUNS.md` for actual contracts and limits.
A real PostgreSQL test exposed a missing type cast in target-specific extraction
claims; the claim now works against PostgreSQL.

**NOT VERIFIED:** authenticated production provider execution and billing,
scheduler and signed delivery. CI/deployment evidence for this continuation belongs
to its exact published head; prior green checks apply only to the prior head.
Complete operator COGS, automations and Live Dataset lineage remain incomplete.
Canonical internal cost columns and future parent fields stay empty rather than
manufacturing values.

### Wave 2 foundation — measured provider cost events

A separate dependent tranche now records trustworthy provider-reported units in
`ih_cost_events`, linked to the canonical run and uniquely identified by their
source usage event. Settlement rollback/idempotency applies to these facts as well.
An operator-authenticated internal read endpoint exposes measured units and
explicitly unknown valuations. Decimal amounts retain precision. See
`OPERATOR_COST_EVENTS.md`.

**PARTIAL:** this is the required internal cost interface, not a finished margin
engine. Reconciled invoices, browser/model/compute/storage costs, full coverage,
spend policies and cost-aware routing remain. Total COGS and margin are not
fabricated. Production operator execution and invoice reconciliation remain
**NOT VERIFIED**.

### Sourced provider-rate revisions and coverage

**Implemented in code:** immutable sourced provider-credit rates with exact decimal
prices, as-of dates and exclusive validity ends; version/revision pinning;
operator-only import/list and bounded historical valuation (preview by default);
unknown/stale/unreviewed valuation reasons; missing quantity/provider/operation
coverage; transactional native Playwright wall-clock measurement on success and
failure. Revisions never reprice existing pinned facts. No guessed prices are
seeded and customer wallet/quote pricing remains unchanged. See
`PROVIDER_COST_RATES.md` for contracts and rollback compatibility.

**PARTIAL:** provider valuations are rate estimates, not invoice reconciliation.
Native browser duration is partial measurement with unknown USD value. Model,
compute, storage, delivery and proxy remain uninstrumented; complete run COGS and
margin remain unknown. Policies and cost-aware routing remain subsequent work.
Production authenticated operator use and sourced invoice reconciliation remain
**NOT VERIFIED**. Verification evidence must match the new published head.
