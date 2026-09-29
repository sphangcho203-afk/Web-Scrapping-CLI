# Capability Economics and Universal Tool Access

OpenCrawl does not use one flat price for every MCP tool call, and subscription tiers do not unlock separate tool catalogs.

## Product model

### 1. Capability access

All standard OpenCrawl plans — Free, Builder, Pro, and Scale — can call the same OpenCrawl tool families and provider classes, including:

- local and public data tools;
- metered and premium provider routes;
- browser execution;
- sandbox execution;
- semantic capability routing;
- Tool Mesh batches within the global safety bound.

The wallet is the execution gate for OpenCrawl-supplied work. If the account can reserve the quoted credits, the subscription tier does not block the tool.

Plans still differ in commercial capacity such as:

- included monthly wallet balance;
- requests per minute;
- concurrent requests;
- API-key count;
- monitor count.

Privacy, authorization, provider configuration, bounded-work validation, and global safety policy remain independent of subscription tier.

### 2. Cost

A request is first quoted from its actual execution shape:

```text
base capability cost
+ provider/API surcharge
+ requested work units
+ batch size
+ runtime/depth/source usage
```

OpenCrawl then applies the hosted wallet burn policy:

```text
wallet charge = raw metered units × OPENCRAWL_CREDIT_BURN_MULTIPLIER
```

The default multiplier is `3`. A raw 10-unit operation therefore reserves up to 30 wallet units. The multiplier is centralized so provider-specific economics can stay grounded in real work while product credit velocity can be tuned independently.

A local metadata lookup remains cheaper than a paid provider call or multi-source investigation.

#### BYO capability rule

OpenCrawl does **not** charge wallet balance for the external capability itself when the user supplies it.

That currently includes:

- user-connected apps executed through the user-scoped connected-account bridge;
- remote MCP servers saved by that user.

Those calls are recorded in usage telemetry with a zero OpenCrawl execution charge. Any fees charged by the connected SaaS, API, MCP operator, or the user's own subscription remain between the user and that provider.

OpenCrawl wallet charges apply when a request consumes OpenCrawl-supplied capability or infrastructure, such as first-party crawling, hosted browser/sandbox runtime, OpenCrawl-funded provider routes, or another explicitly metered OpenCrawl resource.

A BYO route does not become billable merely because it passes through `mesh_execute`, a semantic capability, or a batch.

### 3. Output policy

Output safety and privacy policy is not purchasable. A paid subscription never grants hidden credentials, secrets, private addresses, or otherwise prohibited private records.

Public professional/business information may be returned when the evidence is genuinely public and relevant.

## Current plan capability model

| Capability | Free | Builder | Pro | Scale |
| --- | ---: | ---: | ---: | ---: |
| Tool calling | Yes | Yes | Yes | Yes |
| Provider class | Premium-capable | Premium-capable | Premium-capable | Premium-capable |
| Batch calls | Up to 50 | Up to 50 | Up to 50 | Up to 50 |
| External sources | Up to 12 | Up to 12 | Up to 12 | Up to 12 |
| Max capability depth | 12 | 12 | 12 | 12 |
| Browser | Yes | Yes | Yes | Yes |
| Sandbox | Yes | Yes | Yes | Yes |

These are capability limits, not plan upgrades. Commercial plans differentiate wallet allocation and throughput rather than which tools exist.

## Reservation lifecycle

Customer execution uses a reservation lifecycle:

```text
quote raw work
  -> apply wallet burn multiplier
  -> reserve wallet credits
  -> execute
  -> settle measured raw work × burn multiplier
  -> release unused reservation
  -> persist usage receipt
```

A request cannot reserve more credits than the wallet has available after existing reservations.

Reservations abandoned by a crashed worker are released after a bounded stale interval.

## Routing cannot bypass billing

Meta-tools are unwrapped for pricing.

For example, these must quote the same underlying operation before the wallet multiplier:

```text
phone_number_lookup(...)
mesh_execute(ref="phoneintel:lookup", ...)
mesh_capability_execute(capability="phone.number.lookup", ...)
```

Likewise, `mesh_batch_execute` sums each nested OpenCrawl-supplied call rather than charging one flat batch fee.

## Example raw economics

Local-only phone lookup:

```text
phone_number_lookup
external=false

raw: 2 units
default hosted wallet reservation: 6 units
```

Two configured free-tier enrichers:

```text
providers=["veriphone","abstract"]

raw: 2 base + 2 + 2 = 6 units
default hosted wallet reservation: 18 units
```

Twilio telecom intelligence is available on every standard plan:

```text
providers=["twilio"]

raw: 2 base + 8 = 10 units
default hosted wallet reservation: 30 units
```

External phone enrichment still requires an explicit provider list so the cost is known before execution.

## Raw provider policy

OpenCrawl distinguishes **who supplies the capability**, not just which transport executes it:

- user-connected app: **0 OpenCrawl wallet charge**;
- user-saved remote MCP: **0 OpenCrawl wallet charge**;
- OpenCrawl first-party/native capability: priced from its work units;
- OpenCrawl-provided public/API route: priced by route policy;
- OpenCrawl-funded Firecrawl, Tavily, Exa, RapidAPI, Apify, or similar execution: priced from provider/work budgets;
- operator-managed remote MCP supplied as part of OpenCrawl: may carry an OpenCrawl route charge.

The transport is not the product. A Composio or MCP hop is free when it only carries a capability the user brought; it can be metered when OpenCrawl supplies the underlying resource.

## Receipts and telemetry

Usage events keep:

- plan;
- category;
- provider class;
- raw quoted units;
- credit burn multiplier;
- reservation;
- measured settlement;
- pricing breakdown;
- final charged wallet credits;
- latency;
- input/output bytes;
- request ID.

The MCP HTTP response exposes `X-Credits-Reserved` before execution completes. Final settled cost is authoritative in the usage ledger.

Measured settlement currently covers provider work such as external phone calls, public-search evidence, raw Tool Mesh execution, browser/sandbox runtime, and supported provider-reported usage. The reservation remains a hard upper bound: measured pricing can release unused credits but cannot unexpectedly exceed preflight reservation.

## Design rule for new capabilities

Every substantial new capability should define, before production rollout:

1. provider class;
2. raw base cost;
3. variable work units;
4. maximum bounded reservation;
5. capability-wide depth/source/runtime bounds;
6. privacy/output policy;
7. provider fallback rules;
8. telemetry required to calculate measured cost;
9. whether the capability is user-supplied BYO or OpenCrawl-funded.

Do not introduce subscription-specific tool gates. New capabilities join the shared catalog and are governed by credits, throughput, authorization, configuration, and safety policy.
