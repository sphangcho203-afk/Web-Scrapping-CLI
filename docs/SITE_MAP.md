# Site Map

Open **Site Map** in the OpenCrawl console when you need a site's URL structure before paying to crawl page bodies.

This is the first-class product surface for the existing `web.map.site` semantic capability. The UI and HTTP API use the capability registry, so provider selection remains behind OpenCrawl's routing boundary.

## Why map before crawl

A map is cheaper and lighter than collecting every page. Use it to:

- inventory a public site's reachable URLs;
- focus discovery on docs, pricing, products, jobs or another URL theme;
- inspect hierarchy/depth before choosing a crawl budget;
- save the URL inventory as an account-owned dataset;
- decide which site sections are actually worth crawling.

Mapping is URL discovery. It does **not** promise readable page bodies, JavaScript rendering or structured extraction.

## Workflow

```
site root
  -> validate public target
  -> review maximum reservation
  -> explicit confirmation
  -> reserve wallet funds
  -> web.map.site semantic capability
  -> normalize same-site URLs
  -> classify URL paths
  -> save dataset
  -> settle measured work
  -> release unused reservation
```

The semantic route currently has Firecrawl map and a first-party native fallback. Normal user output does not expose provider-specific response shapes.

## Inputs

| Field | Meaning | Limit |
| --- | --- | --- |
| `url` | Public HTTP(S) site root | required |
| `search` | Optional map focus such as `docs` or `pricing` | 160 characters |
| `limit` | Maximum normalized URLs returned | 1–1000 |
| `include_subdomains` | Allow subdomains of the root host | boolean |
| `sitemap_mode` | `auto`, `only`, or `ignore` | required enum |
| `api_key_id` | Active owned execution key for session callers | required in console |
| `max_charge_credits` | Hard reservation ceiling in internal wallet units | optional API control |
| `quote_revision` | Binds confirmation to reviewed inputs/pricing | optional API control |

For direct API clients using a bearer OpenCrawl key, `api_key_id` is not required unless a key is also explicitly selected.

## Cost review

`POST /api/site-map/quote`

Reviewing performs target validation and pricing only. It does not reserve wallet funds and does not call a map provider.

Example:

```bash
curl --fail-with-body "$OPENCRAWL_ORIGIN/api/site-map/quote" \
  -H "Authorization: Bearer $OPENCRAWL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url":"https://example.com",
    "limit":250,
    "include_subdomains":false,
    "sitemap_mode":"auto"
  }'
```

The response contains the existing quote contract, including:

- maximum reservation;
- current available wallet balance;
- affordability;
- wallet-units-per-USD scale;
- quote revision.

The console always confirms with both a spend ceiling and the quote revision. If the inputs or pricing change, execution returns `quote_changed` and requires a fresh review.

## Execute

`POST /api/site-map/run`

```bash
curl --fail-with-body "$OPENCRAWL_ORIGIN/api/site-map/run" \
  -H "Authorization: Bearer $OPENCRAWL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url":"https://example.com",
    "limit":250,
    "include_subdomains":false,
    "sitemap_mode":"auto",
    "max_charge_credits":500,
    "quote_revision":"REVISION_FROM_QUOTE"
  }'
```

JavaScript:

```javascript
const origin = process.env.OPENCRAWL_ORIGIN;
const headers = {
  Authorization: `Bearer ${process.env.OPENCRAWL_API_KEY}`,
  "Content-Type": "application/json",
};

const input = {
  url: "https://example.com",
  limit: 250,
  include_subdomains: false,
  sitemap_mode: "auto",
};

const quoteResponse = await fetch(`${origin}/api/site-map/quote`, {
  method: "POST",
  headers,
  body: JSON.stringify(input),
});
if (!quoteResponse.ok) throw new Error(await quoteResponse.text());
const { quote } = await quoteResponse.json();

const runResponse = await fetch(`${origin}/api/site-map/run`, {
  method: "POST",
  headers,
  body: JSON.stringify({
    ...input,
    max_charge_credits: quote.maximum_charge_credits,
    quote_revision: quote.quote_revision,
  }),
});
if (!runResponse.ok) throw new Error(await runResponse.text());
console.log(await runResponse.json());
```

Python:

```python
import os
import httpx

origin = os.environ["OPENCRAWL_ORIGIN"].rstrip("/")
headers = {"Authorization": f"Bearer {os.environ['OPENCRAWL_API_KEY']}"}
payload = {
    "url": "https://example.com",
    "limit": 250,
    "include_subdomains": False,
    "sitemap_mode": "auto",
}

with httpx.Client(timeout=45) as client:
    quote = client.post(f"{origin}/api/site-map/quote", headers=headers, json=payload)
    quote.raise_for_status()
    reviewed = quote.json()["quote"]

    run = client.post(
        f"{origin}/api/site-map/run",
        headers=headers,
        json={
            **payload,
            "max_charge_credits": reviewed["maximum_charge_credits"],
            "quote_revision": reviewed["quote_revision"],
        },
    )
    run.raise_for_status()
    print(run.json())
```

## Output

The normalized result includes:

- `root_url`;
- `urls[]`;
- title/description when the mapping route supplied them;
- URL path;
- path depth;
- heuristic category;
- parent URL;
- total/reported URL counts;
- truncation state;
- category counts.

Current URL categories are intentionally simple and deterministic:

- home;
- docs;
- pricing;
- products;
- jobs;
- news;
- company;
- account;
- other.

Classification is based on URL structure only. It does not fetch page content just to classify a URL.

## Dataset behavior

Every successful map attempts to save the normalized `urls` rows through the existing DatasetStore.

The same existing dataset limits apply:

- 2 MB maximum saved envelope;
- 1000 rows;
- JSON, JSONL and CSV export;
- account isolation;
- rename/delete;
- signed `dataset.saved` webhook when configured.

If persistence fails, the map result still returns with an explicit `dataset_not_saved` warning. The execution can still be charged because mapping work already occurred.

## Failure and accounting behavior

- invalid/private targets fail before provider execution;
- an insufficient spending ceiling creates no reservation;
- a changed quote requires review again;
- wallet availability is rechecked transactionally at confirmation;
- fallback provider attempts remain bounded by the reservation;
- final charge cannot exceed the reservation;
- unused reserved credits are released;
- the usage event records `web.map.site` as the semantic capability;
- provider details stay in internal execution telemetry rather than becoming product-facing output.

## Current limitations

This first productized map tranche does **not** yet provide:

- visual graph rendering;
- manual subset selection -> crawl from the map page;
- robots/sitemap diagnostics as a separate report;
- compressed-sitemap expansion in the native fallback;
- page-content classification;
- JavaScript rendering;
- scheduled remapping/change history.

The native fallback currently discovers links from the fetched root page. A configured richer map provider can return a broader inventory. The normalized OpenCrawl contract remains the same.

## Verification gate

Before promotion, verify on the deployed authenticated environment:

1. review a map;
2. lower the spend cap below the review and confirm rejection with no reservation;
3. execute the reviewed map;
4. inspect the saved dataset/export;
5. verify the run is labelled `web.map.site` in Usage;
6. repeat with the same target under provider fallback conditions;
7. verify external dataset webhook receipt when enabled.

Preview/build readiness alone is not production verification.
