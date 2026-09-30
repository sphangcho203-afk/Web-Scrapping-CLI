# Capability workbench

The Capability workbench exposes registered OpenCrawl semantic web capabilities through one browser/API flow:

**discover → inspect schema → review maximum cost → confirm → reserve → execute → settle → save output**

It reuses the existing CapabilityRegistry, Tool Mesh, wallet ledger, execution meter and DatasetStore. It does not create a second provider router.

## Scope

The first release exposes the `web` capability pack. A capability is runnable in the interactive workbench only when:

- it is registered,
- it is read-only,
- at least one configured route is available,
- and every currently available route used by the interactive contract is synchronous.

Asynchronous provider jobs remain visible but are marked unavailable in the interactive workbench until OpenCrawl owns a durable job/polling/result lifecycle for them. This prevents a provider job handle from being presented as a completed OpenCrawl run.

## Discover capabilities

```bash
curl --fail-with-body "$OPENCRAWL_ORIGIN/api/capabilities?pack=web&limit=100" \
  -H "Cookie: <verified web session>"
```

The browser catalog intentionally returns semantic capability metadata, not raw provider candidates.

Inspect one capability:

```bash
curl --fail-with-body "$OPENCRAWL_ORIGIN/api/capabilities/web.map.site" \
  -H "Cookie: <verified web session>"
```

The response includes the normalized input/output schema and:

```json
{
  "availability": {
    "interactive_ready": true,
    "available_routes": 2,
    "reason": null
  }
}
```

Provider identities remain behind the product boundary on this surface.

## Review cost

Quote requests do not reserve credits and do not execute the provider.

```bash
curl --fail-with-body "$OPENCRAWL_ORIGIN/api/capabilities/web.map.site/quote" \
  -X POST \
  -H "Authorization: Bearer $OPENCRAWL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "arguments": {
      "url": "https://example.com",
      "limit": 100
    }
  }'
```

A verified browser session may instead send an owned `api_key_id`.

The quote returns the maximum reservation, `quote_revision`, wallet conversion, current available balance and affordability. The review response is `Cache-Control: no-store`.

## Confirm and run

Use the reviewed maximum and revision:

```bash
curl --fail-with-body "$OPENCRAWL_ORIGIN/api/capabilities/web.map.site/run" \
  -X POST \
  -H "Authorization: Bearer $OPENCRAWL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "arguments": {
      "url": "https://example.com",
      "limit": 100
    },
    "max_charge_credits": 15,
    "quote_revision": "REVIEWED_64_CHARACTER_REVISION"
  }'
```

The server rechecks the caller, current price and wallet inside the existing reservation transaction. A stale revision or insufficient spending ceiling fails before execution.

Successful responses include:

- request ID,
- semantic capability ID,
- normalized result data,
- route-attempt statuses without exposing provider credentials,
- measured credits reserved/charged,
- duration,
- saved dataset metadata when persistence succeeds.

Generic capability outputs are stored as dataset `records`, while the complete bounded result envelope remains attached to the dataset output.

## JavaScript

```javascript
const origin = process.env.OPENCRAWL_ORIGIN;
const key = process.env.OPENCRAWL_API_KEY;

const quoteResponse = await fetch(
  origin + "/api/capabilities/web.map.site/quote",
  {
    method: "POST",
    headers: {
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      arguments: { url: "https://example.com", limit: 100 },
    }),
  },
);
if (!quoteResponse.ok) throw new Error(await quoteResponse.text());
const { quote } = await quoteResponse.json();

const runResponse = await fetch(
  origin + "/api/capabilities/web.map.site/run",
  {
    method: "POST",
    headers: {
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      arguments: { url: "https://example.com", limit: 100 },
      max_charge_credits: quote.credits,
      quote_revision: quote.quote_revision,
    }),
  },
);
if (!runResponse.ok) throw new Error(await runResponse.text());
console.log(await runResponse.json());
```

## Python

```python
import os
import httpx

origin = os.environ["OPENCRAWL_ORIGIN"].rstrip("/")
headers = {"Authorization": f"Bearer {os.environ['OPENCRAWL_API_KEY']}"}
arguments = {"url": "https://example.com", "limit": 100}

with httpx.Client(timeout=90) as client:
    quote = client.post(
        f"{origin}/api/capabilities/web.map.site/quote",
        headers=headers,
        json={"arguments": arguments},
    ).json()["quote"]

    result = client.post(
        f"{origin}/api/capabilities/web.map.site/run",
        headers=headers,
        json={
            "arguments": arguments,
            "max_charge_credits": quote["credits"],
            "quote_revision": quote["quote_revision"],
        },
    )
    result.raise_for_status()
    print(result.json())
```

## Failure behavior

- `capability_not_found` — semantic web capability is not registered.
- `interactive_not_supported` — capability is side-effecting.
- `interactive_not_ready` — current routes are unavailable or asynchronous.
- `invalid_arguments` — arguments is not an object.
- `input_too_large` — body exceeds 128 KB.
- existing wallet errors — insufficient credits, spend ceiling exceeded, quote changed.
- `capability_failed` — no route completed; request ID and measured charge information are returned when available.
- `dataset_not_saved` warning — execution completed but bounded result persistence failed; copy the returned result.

## Why async capabilities are blocked here

A provider returning an external job ID is not the same as OpenCrawl owning the run. The directive requires durable status, cancellation, logs, output persistence and idempotent accounting. URL crawling already has that owned job model. Other async semantic capabilities will be added to this workbench after they use an equivalent OpenCrawl-owned durable execution contract.

## Current limits

- browser workbench pack: `web`
- read-only capabilities only
- request body: 128 KB
- interactive timeout: 60 seconds
- interactive provider wait: 30 seconds
- dataset limits remain 2 MB / 1000 rows
- provider credentials never appear in browser schemas/results

The next extension is to move currently asynchronous semantic capabilities onto an OpenCrawl-owned durable run entity instead of exposing raw upstream jobs.
