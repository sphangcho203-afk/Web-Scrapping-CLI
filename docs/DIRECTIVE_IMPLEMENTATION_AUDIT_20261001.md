# OpenCrawl Maximum-Value Directive — implementation audit

Audit date: 2026-10-01  
Directive baseline: `OPENCRAWL_MAXIMUM_VALUE_IMPLEMENTATION_PROMPT` supplied by the product owner.  
Repository: `sphangcho203-afk/Web-Scrapping-CLI`  
Audited code head: `6f3d99f64d5fe2f4c11860553cbea6d0c51872e2` (`codex/saved-playground-datasets-20260930`).  
Continuation branch: `codex/directive-gap-closure-20261001`.

This document distinguishes code that exists from product behavior that has actually been production-verified. Passing fixtures, CI, or a Vercel build does not satisfy the directive's production quality gate by itself.

## Status vocabulary

- **IMPLEMENTED** — a real repository path exists and the behavior is covered by the current implementation/tests.
- **PARTIAL** — useful implementation exists, but one or more requirements in the directive are absent or only available through a provider/raw tool rather than a coherent OpenCrawl workflow.
- **ADAPTER ONLY** — a backend/provider capability exists, but it is not yet a complete first-class user workflow.
- **NOT FOUND** — no current end-to-end implementation was found in the audited code.
- **NOT PRODUCTION-VERIFIED** — code/CI exists, but the live authenticated flow has not been demonstrated for this audited head.

## 1. Product principles

| Directive requirement | Status | Repository evidence / gap |
| --- | --- | --- |
| Broad tool access; credits meter usage instead of plan-gating ordinary tools | IMPLEMENTED | Main `56ca429` moved all plans to the same catalog. `docs/SAAS_CONTROL_PLANE.md` documents wallet/throughput differentiation rather than ordinary tool availability. |
| Real credits, reservations and settlement | IMPLEMENTED | `ControlStore.reserve_tool_call` and terminal/idempotent settlement in `control_store.py`; PR #45 adds quote revisions and spend ceilings. |
| No fake usage graphs | IMPLEMENTED for usage | `usage_intelligence.py` reads the canonical ledger; `web/usage-intelligence.js` renders the server series and exact tables. |
| No fake/dead capability surfaces | PARTIAL | The semantic registry contains capabilities that are not all exposed as first-class user workflows. This audit is closing that gap rather than adding more inventory. |
| Secrets stay server-side | IMPLEMENTED in audited connection/tool paths | MCP/connected-app secret material is stored separately from public connection config; provider keys are injected server-side. |
| Production behavior verified before calling a capability shipped | NOT PRODUCTION-VERIFIED for PR #45 tranche | PR #45 explicitly leaves authenticated deployed execution, worker completion, dataset/export, monitor transitions and invoice reconciliation as release gates. |

## 2. Phase 0 — current product audit

| Area | Status | Notes |
| --- | --- | --- |
| Application structure | IMPLEMENTED / audited incrementally | FastAPI SaaS app with control, auth, billing, rewards, usage, monitoring, datasets, crawl workers, provider/tool mesh, MCP gateway and static browser UI. |
| Auth flows | PARTIAL verified | Email/password, verification, recovery, session, TOTP and OAuth/MCP code paths exist. Full live production verification is outside CI evidence for the current tranche. |
| API keys | IMPLEMENTED | Create, scoped use and revoke paths exist with UI. |
| Playground | IMPLEMENTED for search/research/URL crawl | Quote -> confirm -> reserve -> execute -> settle -> persist exists on PR #45. |
| Wallet / rewards | IMPLEMENTED core | Balance, monthly/purchased/reserved credits, live top-up/billing infrastructure and community reward redemption are in main. |
| Usage/run history | IMPLEMENTED core | Canonical ledger and run detail exist. Background crawl jobs are a separate durable entity. |
| Current-state map requested by directive | PARTIAL | `docs/VALUE_IMPLEMENTATION_AUDIT.md` maps the first collection tranche. There is not yet one generated whole-product feature->UI->endpoint->service->provider->DB->events->credits->output inventory. |

## 3. Phase 1 — market / demand research

**PARTIAL.**

`docs/VALUE_IMPLEMENTATION_AUDIT.md` records targeted competitor research (Apify, Firecrawl, Zyte, Tavily, Browserless) and uses it to prioritize durable outputs, monitoring and delivery. It explicitly states that a full market survey, aggregate user-demand loop and willingness-to-pay validation remain outstanding.

The directive's broader research set (Bright Data, Oxylabs, ScrapingBee, Crawlbase, Browserbase, Reddit/HN/forum demand aggregation, pricing/changelog comparison and a complete capability matrix) has not been completed as one evidence-backed research artifact.

## 4. Product primitives

### Search — PARTIAL / strong core

Implemented:
- Live search providers and semantic search capabilities.
- Ranked result objects rather than URL-only output.
- Native Brave path supports count, country, language and freshness.
- Firecrawl search exposes bounded provider options including domains/categories where supported.
- Playground search/research saves output as a dataset and now supports cost review.

Missing / incomplete:
- One normalized OpenCrawl Search schema does not yet expose every directive option consistently across provider fallbacks.
- Search is not yet a durable background job like URL crawl.
- Search->structured extraction composition is not a first-class workflow.

### Smart Scrape — PARTIAL / engine exists, workflow incomplete

Implemented:
- `web.fetch.page` semantic capability.
- Firecrawl scrape can return Markdown/HTML/structured formats and provider-supported screenshots/highlights/questions.
- Fallback candidates include Apify and first-party native HTTP fetch.
- Tool Mesh handles provider health/reliability and fallback for read-only capabilities.

Missing / incomplete:
- No dedicated Smart Scrape product surface with a normalized OpenCrawl input contract.
- The system does not yet expose one cost-aware "HTTP first -> render if needed -> provider fallback" decision trace as a user-facing primitive.
- Result tabs/formats are not unified as directed.
- User-owned rendered-session controls are not part of this flow.

### Structured Extract — ADAPTER ONLY / PARTIAL

Implemented:
- `web.extract.structured` semantic capability exists.
- Firecrawl Agent is used as a bounded preferred path; legacy unbounded extract is deliberately rejected in `firecrawl_provider.py`.

Missing / incomplete:
- No first-class schema/natural-language extraction workflow in the main dashboard.
- No consistent dataset/search/crawl -> extract action.
- No explicit field-level validation/provenance UI across all extraction routes.

### Question / Highlights — ADAPTER ONLY

Provider-level scrape options can request questions/highlights, but no OpenCrawl page/dataset Q&A primitive matching the directive was found.

### Crawl — PARTIAL / strong implementation

Implemented:
- Immediate bounded URL crawl.
- Durable owned background crawl jobs.
- Idempotent create/reservation, worker lease fencing, resumable committed frontier, cooperative cancellation.
- Robots, SSRF/public-network checks, canonical handling, include/exclude paths, subdomains, query policy, sitemap discovery.
- Saved readable content datasets and exports.
- Progress data includes pages/discovery/success/failure/truncation and credit reservation/charge.

Missing / incomplete:
- No pause/resume user control; only durable recovery and cancellation.
- No JavaScript-rendered crawl in the owned background crawler.
- No large multi-tick scheduled crawl for jobs larger than one bounded execution window.
- No crawl page-graph product output.
- No crawl-level extraction schema pipeline.
- No durable background search/research jobs.

### Map — ADAPTER ONLY / PARTIAL

Implemented:
- `web.map.site` semantic capability with Firecrawl and first-party fallback.
- Native fallback currently returns bounded links from a fetched page.

Missing / incomplete:
- No dedicated Map workflow.
- No hierarchy/classification/clustering/select-subset-for-crawl experience.
- Native fallback is not a full site mapper.

### Browser / Interact — PARTIAL

Implemented:
- Browser-oriented provider/back-end definitions.
- Semantic `browser.navigate` capability.
- Firecrawl interact support for a prior scrape session.
- Playwright/browser backend infrastructure exists.

Missing / incomplete:
- No coherent first-class Browser Task flow matching render/click/type/scroll/wait/screenshot/extract.
- No complete user-owned authenticated browser profile/session lifecycle in the audited product surface.
- Browser execution is not unified with the durable owned Run model.

### Monitors — PARTIAL / page-text monitoring implemented

Implemented:
- Owned content monitor scheduling using the durable crawl queue.
- Baseline / unchanged / changed / failed history.
- Server-rendered text/title comparison.
- Datasets and signed dataset webhook notifications for baseline/change.
- Configuration version fencing, key ownership/revocation checks and actual credit history.

Missing / incomplete:
- Field/selector monitors.
- Search-query monitors.
- Structured-field and threshold diffing.
- Semantic text diff.
- Price/stock/job-specific monitor templates.
- Email/Slack/Discord/Telegram actions as monitor outputs.
- Append-to-one-history-dataset behavior.

### Datasets — PARTIAL / core implemented

Implemented:
- Account-owned saved outputs.
- Rows, columns, request/run relation, source records, timestamps.
- Search/filter/pagination.
- Rename/delete.
- JSON/JSONL/CSV export.
- Signed completion webhook delivery.

Missing / incomplete:
- Markdown/XML/XLSX export.
- Column visibility controls as a durable preference.
- Rerun-source action.
- Monitor append/history dataset model.
- General connector delivery beyond webhooks/download.
- Retention policy controls.

### Data delivery / connectors — PARTIAL

Implemented:
- Signed HTTPS dataset webhooks with retry/lease recovery and delivery history.
- Connected applications and remote MCP infrastructure exist separately.

Missing / incomplete:
- Destination abstraction covering S3/R2, PostgreSQL, Supabase, Neon, Sheets and email.
- Per-destination schema mapping and connection tests in one delivery system.

### Automations — ADAPTER ONLY

The semantic registry contains automation workflow adapters (for configured external workflow systems), but the directive's native step-based Trigger -> Action -> Filter -> Output workflow model was not found.

### Tools / recipes — NOT FOUND as directed

Tool Mesh/capability registry exists, but a reusable recipe product with versioned input/output schema, cost model, examples, ownership and health state is not implemented as a product library.

### MCP / agent access — IMPLEMENTED core, production verification still matters

Implemented:
- Streamable HTTP MCP gateway.
- Semantic capability registry.
- Raw tool discovery/description/execute and semantic resolve/execute.
- Scoped API keys.
- OAuth authorization-server/protected-resource metadata and authorization/token paths.
- Remote MCP connections with server-held credentials.

Remaining:
- Continue deployed-client verification across supported hosts.
- Keep UI claims constrained to actually working OAuth/client combinations.
- Capability workbench below will reduce the mismatch between MCP-callable functions and browser UI workflows.

## 5. Vertical data products

**PARTIAL.**

Gaming/repository/public-data surfaces are substantial and callable. Developer/public-data extraction exists. The directive's evidence-driven business/leads, ecommerce, jobs, news and SERP vertical templates are not implemented as a coherent recipe/product family. Do not inflate this into "100+ tools"; build templates after the primitive execution surface is complete.

## 6. Unified execution engine

**PARTIAL.**

Existing execution state is split among:
- canonical usage events/reservations,
- immediate Playground requests,
- durable `ih_crawl_runs`,
- monitor history/jobs,
- provider-native async jobs.

This is not yet the directive's one durable `RUN` entity for every capability. Background crawl is the strongest implementation of the desired run semantics. A future migration should converge behavior without destructively rewriting stable accounting.

## 7. Credit / wallet / monetization

**IMPLEMENTED core; operator economics incomplete.**

Implemented:
- Exact internal integer accounting.
- Monthly/purchased/reserved balances.
- Pre-run quote and maximum charge on the PR #45 Playground/crawl flow.
- Atomic reservation/settlement and idempotent terminal settlement.
- Retry headroom only for replay-safe work.
- Reward/community-code redemption with server-side controls.

Missing / incomplete:
- Complete provider invoice/native compute/payment-fee reconciliation.
- Margin by capability.
- Per-key/daily spend budgets.
- Historical wallet-balance analytics.
- Automatic pricing feedback from measured operator COGS.

## 8. UX / information architecture

**PARTIAL.**

Implemented real surfaces include Overview, Playground, Datasets, Background crawls, Public data, Game Intelligence, Repositories, Runs, Monitors, Connections, Wallet, Rewards, Billing, API keys and Settings.

The primary mismatch is that semantic capabilities such as site map, batch scrape and structured extraction can exist in the registry without an equivalent first-class generic execution surface. This continuation branch addresses that gap before creating more specialized pages.

## 9. Documentation

**PARTIAL / substantial.**

There are detailed docs for control plane, MCP, Firecrawl, capability economics, datasets, webhooks, durable crawl, monitors, discovery, usage and execution budgets.

Remaining:
- Docs are not generated/synchronized from the capability registry as the directive requests.
- Not every callable semantic capability has a complete curl + JS + Python workflow.
- Product-level Smart Scrape/Extract/Map guides need to follow the new common execution surface.

## 10. Provider abstraction

**IMPLEMENTED strongly.**

`ToolProvider` / Tool Mesh plus `CapabilityRegistry` provide normalized discovery, provider status, semantic candidates, health-aware read-only fallback, provider execution and normalized schemas. This is more general than separate SearchProvider/ScrapeProvider interfaces and should be preserved rather than rewritten.

Remaining:
- expose operator cost metadata and margin decisions more directly to routing once trustworthy COGS exists.

## 11. Reliability

**IMPLEMENTED strongly but not universal.**

Existing code covers typed/normalized errors in many boundaries, request IDs, reservations, replay-safe retries, provider reliability/circuit state, bounded concurrency, health, webhook retries/signing, SSRF policies, output limits, cancellation, durable crawl recovery, DB transaction safety and credit atomicity.

Remaining:
- unify these semantics across every capability family and future native automation/browser runs.
- explicit dead-letter/operator recovery surfaces are not consistently productized.

## 12. Observability

**PARTIAL.**

Implemented:
- Ledger-backed request, credit, latency, status/provider/tool breakdowns.
- Responsive exact usage charts and run inspection.
- Provider health/reliability infrastructure.

Missing:
- gross provider/infrastructure cost,
- margin by capability,
- conversion,
- repeat usage,
- successful-first-run funnel,
- complete adoption metrics,
- browser/crawl/webhook reliability dashboards,
- per-key filters and comparison periods.

## 13. Feedback / user-demand loop

**NOT FOUND.**

No first-class persisted feature-request / failed-job-feedback / missing-integration / requested-vertical loop with grouping by frequency, account value, capability and severity was found.

## 14. Testing and product quality gate

PR #45 reports green CI for the exact audited head:
- Python 3.11/3.12/3.13: 706 passed, 46 environment-dependent skips.
- real PostgreSQL: 95 passed.
- shipped Chromium runtime: 27 passed.
- lint/compile/JS syntax passed.

That is strong repository verification, but the directive explicitly requires production behavior verification. PR #45 itself says the authenticated deployed quote -> confirm -> worker -> saved/exported result -> wallet/Usage flow and monitor baseline -> unchanged -> changed flow still require live verification.

Therefore the new PR #45 capabilities should be described as **implemented and CI-verified, not production-verified**.

## 15. Next coherent implementation tranche

Do not add another disconnected provider.

The next highest-value gap is:

**Capability registry -> generic user workbench -> quote -> confirm -> reserve -> execute -> measured settlement -> saved dataset -> run trace**

Scope the first release to safe read-only `web.*` capabilities. This immediately productizes existing Search, page fetch/scrape, Map, Crawl, batch scrape, research and Structured Extract adapters without duplicating provider-specific business logic.

Required properties:
1. list only real registered capabilities;
2. show current availability and actual schema from resolved candidates;
3. schema-driven arguments plus raw JSON fallback;
4. read-only quote endpoint using existing `mesh_capability_execute` economics;
5. explicit spend confirmation;
6. execute under the selected owned API key;
7. preserve provider fallback and measured settlement;
8. persist generic outputs as datasets where bounded;
9. expose request ID, credits, attempts/source trace and errors;
10. document the contract and test invalid auth/input/credits/failure/persistence.

After that, the next primitives should be native automation composition and operator COGS/margin telemetry, not feature-count expansion.
