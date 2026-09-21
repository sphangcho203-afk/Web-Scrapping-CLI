# Capability Economics and Subscription Privileges

Internet Hands does not use one flat price for every MCP tool call.

## Three independent policy axes

### 1. Access

A subscription controls execution capacity such as:

- provider classes;
- browser and sandbox access;
- external source count;
- batch size;
- research depth;
- concurrency/rate limits.

Higher plans receive broader execution privileges. Privacy boundaries do not change with plan.

### 2. Cost

A request is quoted from its actual execution shape:

```text
base capability cost
+ provider/API surcharge
+ requested work units
+ batch size
+ runtime/depth/source usage
```

A local metadata lookup therefore costs less than a paid provider call or a multi-source investigation.

### 3. Output policy

Output safety/privacy policy is not purchasable. A higher subscription may unlock more providers, sources, runtime and depth, but never hidden credentials, secrets, private addresses, or other prohibited private records.

Public professional/business information may be returned when the evidence is genuinely public and relevant.

## Current plan privilege model

| Privilege | Free | Builder | Pro | Scale |
| --- | ---: | ---: | ---: | ---: |
| Tool calling | Yes | Yes | Yes | Yes |
| Provider class | Public | Free-tier | Metered | Premium |
| Batch calls | 3 | 10 | 20 | 50 |
| External sources | 0 | 3 | 6 | 12 |
| Max depth | 1 | 3 | 6 | 12 |
| Browser | No | Yes | Yes | Yes |
| Sandbox | No | No | Yes | Yes |

The Free tier remains a real MCP tier: local and public tool execution is available within its credit/rate limits.

## Reservation lifecycle

MCP execution uses a reservation lifecycle:

```text
quote
  -> privilege check
  -> reserve estimated credits
  -> execute
  -> settle actual credits
  -> release unused reservation
  -> persist usage receipt
```

A request cannot reserve more credits than the wallet has available after existing reservations.

Reservations abandoned by a crashed worker are released after a bounded stale interval.

## Routing cannot bypass billing

Meta-tools are unwrapped for pricing.

For example, these must quote the same underlying operation:

```text
phone_number_lookup(...)
mesh_execute(ref="phoneintel:lookup", ...)
mesh_capability_execute(capability="phone.number.lookup", ...)
```

Likewise, `mesh_batch_execute` sums the quoted cost of each nested call rather than charging a single flat batch fee.

## Phone intelligence examples

Local-only lookup:

```text
phone_number_lookup
external=false

2 credits
```

Builder with two configured free-tier enrichers:

```text
providers=["veriphone","abstract"]

2 base + 2 + 2 = 6 credits
```

Pro with Twilio telecom intelligence:

```text
providers=["twilio"]

2 base + 8 = 10 credits
```

External phone enrichment requires an explicit provider list so the cost is known before execution.

## Raw provider examples

Current policy differentiates raw Tool Mesh providers instead of treating all provider calls as equivalent:

- first-party/native provider: low/no surcharge;
- public API/OpenAPI: small surcharge;
- remote MCP: small surcharge;
- Composio: metered surcharge;
- Firecrawl/RapidAPI: higher metered surcharge;
- Apify: higher metered surcharge.

These values are policy inputs, not permanent constants. They can evolve as real provider costs and product economics become clearer.

## Receipts and telemetry

Usage events keep:

- plan;
- category;
- provider class;
- reservation;
- settlement;
- pricing breakdown;
- final charged credits;
- latency;
- input/output bytes;
- request ID.

The MCP HTTP response exposes `X-Credits-Reserved` before execution completes. Final settled cost is authoritative in the usage ledger.

## Design rule for new capabilities

Every substantial new capability should define, before production rollout:

1. minimum plan;
2. provider class;
3. base cost;
4. variable work units;
5. maximum reservation;
6. plan-specific depth/source/runtime limits;
7. privacy/output policy;
8. provider fallback rules;
9. telemetry required to calculate actual cost.

This keeps new tools from creating independent billing and entitlement logic.
