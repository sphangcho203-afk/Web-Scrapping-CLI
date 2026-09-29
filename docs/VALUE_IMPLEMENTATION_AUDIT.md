# OpenCrawl value implementation — first tranche

Audit baseline: `56ca429af5913c5a7895073a0b806733fb4ede9e`, 29 September 2026 UTC. This is a focused execution/storage audit, not a claim that every authentication, billing and production flow has been revalidated.

## Observed flow

| Capability | UI | Endpoint | Execution | Accounting | Prior output persistence |
|---|---|---|---|---|---|
| Search | Playground | POST /api/playground/run | Brave discovery with configured fallback | reserve_tool_call → finish_usage | Returned only |
| Research | Playground deep toggle | Same endpoint, operation research | Search → bounded evidence → extractive synthesis → crawl | Existing measured settlement | Returned only |
| Crawl | Playground URL mode | Same endpoint, operation crawl | Policy/robots → bounded native crawl | Existing measured settlement | Page metadata returned only |
| Run history | Runs | /api/usage/intelligence and /api/usage/runs/{id} | UsageIntelligence | Stored usage events | Cost/log metadata, not collection output |
| Monitors | Monitors | /api/monitors and lifecycle routes | Scheduler/executor modules | Existing monitor accounting | Monitor run records |
| Rewards | Rewards | rewards router | Server-side redemption | Wallet/points ledger | Existing redemption records |

The product already has substantial primitives. Its architecture document still describes early v0.2 layers while the actual SaaS app registers v0.7 control, security, usage, reward, provider and monitor modules. Replacing this substrate would discard useful work.

The chosen gap was durable output: Playground requests produced collected records but no account-owned dataset. The new path is UI → same authenticated execution → existing wallet reservation → collection → DatasetStore → ih_datasets → existing settlement → result plus saved-output link. This change does not introduce a second billing system.

## Research evidence and priority

Sources inspected through current web search:

- Apify documents run-associated datasets, tables, exports and API access: https://docs.apify.com/storage and https://docs.apify.com/storage/dataset
- Firecrawl presents composable search/scrape/interact for research, RAG, competitive intelligence and price monitoring: https://www.firecrawl.dev/
- Firecrawl monitoring covers pages, sites and queries: https://www.firecrawl.dev/monitor
- Developer request for finished-crawl delivery without polling: https://github.com/firecrawl/firecrawl/issues/488 (historical evidence, not a current unresolved-status claim).
- Zyte documents structured extraction for products/job postings and browser versus HTTP extraction sources: https://docs.zyte.com/zyte-api/usage/reference.html
- Tavily offers live search and extraction setup: https://docs.tavily.com/documentation/quickstart
- Browserless documents browser extraction: https://docs.browserless.io/browserql/use-cases/scrape-and-extract-data

These establish competitor capability patterns; they do not prove OpenCrawl customers' willingness to pay. Priority and revenue potential below are qualitative engineering hypotheses. A full market survey across every provider and an aggregate user-demand loop remain outstanding.

| Capability | User problem / target | Frequency | Complexity / marginal cost | Credits | Revenue hypothesis / differentiation | Status / priority |
|---|---|---|---|---|---|---|
| Saved datasets / exports | Developers need reusable outputs after a run | Every useful collection | Low–medium; bounded DB storage | Existing collection charge; reads no extra charge | Improves adoption and saves repeated collection; source records plus run cost | Implemented first |
| Full crawl content | RAG developers need text rather than status metadata | Per crawl | Medium; normalization/storage | Meter fetched pages and bytes | Necessary for docs-to-RAG recipes | Next core gap |
| Webhook delivery | Automation users avoid polling/manual downloads | Every scheduled run | Medium; durable retry/signature/egress controls | Transparent delivery cost if added | Repeat usage and workflow integration | Next retention wave |
| Monitor dataset appends | Pricing/job/news users need history | Hourly–weekly | Medium; dedupe and storage lifecycle | Existing monitored collection plus explicit storage policy | Retention and historical value | Planned, not advertised as shipped |
| Schema extraction | Ecommerce/jobs users need normalized fields | Batch/recurring | Medium–high; optional model/provider costs | Reserve by bounded inputs; settle actual usage | Commercial outputs with provenance | Existing tool paths require deeper audit before unification |
| Browser recipes | Authorized interactive collection | Task-dependent | High; browser/session cost | Higher compute charge | High-value tasks, existing browser substrate | Existing paths; not changed |

## Implemented

- Additive dataset schema with owned usage-request linkage and request uniqueness.
- Automatic Playground output save; empty and partial results retained.
- List/detail/filter/pagination, rename/delete, JSON/JSONL/CSV export APIs.
- Session and scoped API-key access; account isolation; safe CSV and headers.
- Desktop/sidebar and mobile More navigation; saved-result links; dataset controls.
- Public console docs and detailed API guide.

## Limits and remaining mandate

No production DB credentials were needed for development. Tests use an isolated database and provider fixtures. Production authentication/provider execution, previews and promotion require their own verification. This tranche does not fulfill the full attached multi-wave directive: complete market research, whole-product audit, asynchronous runs/cancellation, extraction unification, monitor delivery and automation composition remain future work. No placeholder routes for those capabilities were introduced.
