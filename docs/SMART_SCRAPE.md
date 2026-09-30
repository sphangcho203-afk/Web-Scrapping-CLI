# Smart Scrape

Open **Smart Scrape** when you want one public page turned into clean, reusable content without choosing an upstream scraping provider yourself.

The product has three execution modes:

- **Auto** — begin with OpenCrawl's bounded first-party HTTP extractor and fall back to a rendered extraction route only when the native capture is insufficient.
- **HTTP only** — use only the first-party HTTP extractor. This is the cheapest predictable path and never starts a rendered provider.
- **Rendered** — use the configured rendered extraction capability for JavaScript-heavy pages, screenshots, clean rendered HTML, mobile rendering or wait controls.

All three modes use the same semantic capability execution, wallet reservation, usage ledger, dataset and error contracts.

## Why Smart Scrape

Most pages do not need a browser. Starting every collection with Chromium or a premium upstream wastes time and credits.

Smart Scrape separates the intent — "scrape this page" — from the execution method:

\`\`\`
public URL
  -> validate target
  -> normalize requested formats/options
  -> review maximum reservation
  -> explicit confirmation
  -> reserve wallet funds
  -> choose semantic scrape route
  -> HTTP extraction or rendered fallback
  -> normalize OpenCrawl output
  -> save dataset
  -> settle measured work
  -> release unused reservation
\`\`\`

Provider identity stays in internal execution telemetry. Normal product output describes the route as \`http\` or \`rendered\`.

## Inputs

| Field | Meaning | Limits/default |
| --- | --- | --- |
| \`url\` | Public HTTP(S) page | required |
| \`mode\` | \`auto\`, \`http\`, \`rendered\` | default \`auto\` |
| \`formats\` | Requested output formats | 1–5 |
| \`only_main_content\` | Prefer main readable content | default true |
| \`timeout_ms\` | Execution timeout | 1,000–60,000 |
| \`max_bytes\` | HTTP response ceiling | 32 KB–8 MB |
| \`wait_ms\` | Render wait before extraction | 0–10,000 |
| \`mobile\` | Mobile rendering hint | boolean |
| \`max_age_ms\` | Rendered-provider cache allowance | 0–86,400,000 |
| \`max_charge_credits\` | Hard wallet reservation ceiling | optional API control |
| \`quote_revision\` | Binds confirmation to reviewed price/input | optional API control |

Supported product formats:

- \`markdown\`
- \`links\`
- \`raw_html\`
- \`html\` — rendered path
- \`screenshot\` — rendered path

Requesting \`html\`, \`screenshot\`, mobile rendering, a nonzero wait, or provider cache controls in **Auto** mode routes directly to rendered execution. OpenCrawl does not charge for a pointless HTTP probe first.

Those options are rejected in **HTTP only** mode before execution.

## Cost review

\`POST /api/scrape/quote\`

Reviewing validates and normalizes the request and returns the maximum reservation. It does not reserve funds or start a scrape.

\`\`\`bash
curl --fail-with-body "$OPENCRAWL_ORIGIN/api/scrape/quote" \
  -H "Authorization: Bearer $OPENCRAWL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url":"https://example.com/pricing",
    "mode":"auto",
    "formats":["markdown","links"],
    "only_main_content":true,
    "timeout_ms":30000,
    "max_bytes":2000000
  }'
\`\`\`

The quote includes:

- maximum reservation;
- current available balance;
- affordability;
- wallet-units-per-USD scale;
- quote revision;
- normalized execution plan.

Auto mode reserves enough headroom for the eligible fallback chain. Final settlement uses measured work and cannot exceed the reservation.

## Execute

\`POST /api/scrape/run\`

\`\`\`bash
curl --fail-with-body "$OPENCRAWL_ORIGIN/api/scrape/run" \
  -H "Authorization: Bearer $OPENCRAWL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url":"https://example.com/pricing",
    "mode":"auto",
    "formats":["markdown","links"],
    "only_main_content":true,
    "timeout_ms":30000,
    "max_bytes":2000000,
    "max_charge_credits":500,
    "quote_revision":"REVISION_FROM_QUOTE"
  }'
\`\`\`

JavaScript:

\`\`\`javascript
const origin = process.env.OPENCRAWL_ORIGIN;
const headers = {
  Authorization: \`Bearer \${process.env.OPENCRAWL_API_KEY}\`,
  "Content-Type": "application/json",
};

const input = {
  url: "https://example.com/pricing",
  mode: "auto",
  formats: ["markdown", "links"],
  only_main_content: true,
  timeout_ms: 30000,
  max_bytes: 2000000,
};

const reviewResponse = await fetch(\`\${origin}/api/scrape/quote\`, {
  method: "POST",
  headers,
  body: JSON.stringify(input),
});
if (!reviewResponse.ok) throw new Error(await reviewResponse.text());
const { quote } = await reviewResponse.json();

const runResponse = await fetch(\`\${origin}/api/scrape/run\`, {
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
\`\`\`

Python:

\`\`\`python
import os
import httpx

origin = os.environ["OPENCRAWL_ORIGIN"].rstrip("/")
headers = {"Authorization": f"Bearer {os.environ['OPENCRAWL_API_KEY']}"}
input_data = {
    "url": "https://example.com/pricing",
    "mode": "auto",
    "formats": ["markdown", "links"],
    "only_main_content": True,
    "timeout_ms": 30_000,
    "max_bytes": 2_000_000,
}

with httpx.Client(timeout=90) as client:
    reviewed = client.post(
        f"{origin}/api/scrape/quote",
        headers=headers,
        json=input_data,
    )
    reviewed.raise_for_status()
    quote = reviewed.json()["quote"]

    run = client.post(
        f"{origin}/api/scrape/run",
        headers=headers,
        json={
            **input_data,
            "max_charge_credits": quote["maximum_charge_credits"],
            "quote_revision": quote["quote_revision"],
        },
    )
    run.raise_for_status()
    print(run.json())
\`\`\`

## Output

OpenCrawl returns one normalized page document rather than leaking an upstream-specific response:

- source URL;
- HTTP status when supplied by the execution route;
- content type when known;
- title;
- description;
- readable text;
- Markdown when requested;
- clean rendered HTML when requested and supported;
- raw HTML when requested;
- links;
- screenshot HTTPS URL when requested and supported;
- capture/hash metadata when available;
- execution path: \`http\` or \`rendered\`.

The response also includes:

- request ID;
- reserved credits;
- final charged credits;
- text-byte and link counts;
- saved dataset metadata when persistence succeeds.

## Native HTTP path

The first-party native route:

1. enforces OpenCrawl's public-network/SSRF policy;
2. follows bounded redirects;
3. limits response bytes;
4. accepts textual HTTP content;
5. extracts title, description, headings, links and readable text;
6. uses Trafilatura Markdown extraction when the optional parser is installed;
7. falls back to normalized readable text otherwise.

In Smart/Auto mode, a capture that looks like a JavaScript application shell with too little readable text returns a route failure, allowing the semantic registry to try the rendered candidate.

HTTP-only mode deliberately disables that escalation.

## Dataset behavior

Every successful scrape attempts to save one \`pages\` row through the existing DatasetStore.

Existing dataset behavior applies:

- 2 MB maximum saved envelope;
- 1000-row ceiling;
- JSON, JSONL and CSV export;
- account isolation;
- rename/delete;
- signed \`dataset.saved\` webhook when configured.

A dataset failure does not erase a successfully returned live scrape. The response carries the existing \`dataset_not_saved\` warning because execution work may already have been charged.

## Failure and accounting

- invalid/private targets fail before provider execution;
- incompatible HTTP-only options fail before reservation/execution;
- an insufficient maximum-spend ceiling creates no execution reservation;
- stale quote revisions require a new review;
- current wallet availability is rechecked during confirmation;
- Auto reserves bounded fallback headroom;
- measured settlement charges only observed eligible work inside the reservation;
- unused reserved funds return to the wallet;
- retries/semantic fallback are bounded by the existing Tool Mesh reliability policy;
- the usage ledger records the semantic capability used for the run.

## Current limitations

This tranche does not yet provide:

- user-defined CSS selectors;
- structured JSON schema extraction — that is the next separate primitive;
- authenticated user-owned browser sessions;
- arbitrary interaction steps such as click/type/scroll;
- screenshot binary storage inside DatasetStore;
- multiple-URL scrape in this synchronous endpoint;
- durable asynchronous scrape jobs;
- page-level question/highlight UI;
- automatic route choice based on historical per-domain success/cost.

Use Background Crawls for durable multi-page collection. Structured Extract remains a separate implementation tranche.

## Verification gate

Before promotion, verify on the deployed authenticated environment:

1. Auto mode on a normal server-rendered page uses the HTTP path;
2. Auto mode on a JavaScript shell falls back to rendered execution;
3. screenshot request skips the HTTP probe;
4. HTTP-only mode rejects screenshot/render-only controls before reservation;
5. quote revision and maximum spend are enforced;
6. successful result saves/exports as a dataset;
7. Usage labels the semantic scrape capability and reconciles the final charge;
8. external dataset webhook receipt succeeds when enabled.

Passing CI and preview deployment do not replace this production behavior check.
