# Structured Extract

Structured Extract turns one to twenty public web pages into durable structured output.

The product flow is:

**validate targets -> review wallet ceiling -> confirm -> reserve -> launch owned run -> poll provider privately -> validate returned structure -> save dataset -> settle measured usage**

Unlike an interactive scrape, extraction can outlive the browser request. OpenCrawl therefore exposes an OpenCrawl run ID and keeps any upstream provider job ID private.

## Inputs

- `urls`: 1-20 public HTTP(S) URLs.
- `prompt`: 3-4000 characters describing the fields or facts to extract.
- `schema`: optional JSON Schema object, limited to 32 KB and bounded nesting.
- `effort`: `low`, `medium`, or `high`.
- `api_key_id`: optional owned execution key when called from a verified browser session.

Private-network targets and credential-bearing URLs are rejected through the same public-target policy used by other OpenCrawl collection primitives.

OpenCrawl derives the upstream extraction budget from effort. The browser does not send a provider-specific budget.

## 1. Review the maximum wallet charge

```bash
curl --fail-with-body "$OPENCRAWL_ORIGIN/api/extract/quote" \
  -X POST \
  -H "Authorization: Bearer $OPENCRAWL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "urls": ["https://example.com/pricing"],
    "prompt": "Extract plan name, monthly price and currency.",
    "effort": "medium",
    "schema": {
      "type": "object",
      "properties": {
        "plans": {"type": "array"}
      }
    }
  }'
```

The quote is read-only: it does not reserve credits and does not start provider work.

## 2. Confirm and create a durable run

Send the reviewed `quote_revision`, your accepted `max_charge_credits`, and an idempotency key:

```bash
curl --fail-with-body "$OPENCRAWL_ORIGIN/api/extract/runs" \
  -X POST \
  -H "Authorization: Bearer $OPENCRAWL_API_KEY" \
  -H "Idempotency-Key: extract-pricing-2026-10-01" \
  -H "Content-Type: application/json" \
  -d '{
    "urls": ["https://example.com/pricing"],
    "prompt": "Extract plan name, monthly price and currency.",
    "effort": "medium",
    "max_charge_credits": 1500,
    "quote_revision": "REVIEWED_64_CHARACTER_REVISION"
  }'
```

OpenCrawl creates the reservation and owned run transactionally. The server then attempts the first launch immediately. If the upstream work remains asynchronous, the returned run is normally `waiting`.

Repeating the same idempotency key with the same inputs returns the same run. Reusing it with different inputs returns an idempotency conflict.

## 3. Inspect a run

```bash
curl --fail-with-body "$OPENCRAWL_ORIGIN/api/extract/runs/caprun_EXAMPLE" \
  -H "Authorization: Bearer $OPENCRAWL_API_KEY"
```

Public run states are:

- `queued`: accepted but not yet launched.
- `running`: a fenced worker currently owns the run.
- `waiting`: upstream extraction is active and OpenCrawl will poll it.
- `completed`: terminal structured output was saved.
- `failed`: terminal failure with a stable OpenCrawl error code.
- `cancelled`: cancelled before upstream work started.

The response never contains the provider name or upstream provider job ID.

## 4. Cancellation semantics

```bash
curl --fail-with-body "$OPENCRAWL_ORIGIN/api/extract/runs/caprun_EXAMPLE/cancel" \
  -X POST \
  -H "Authorization: Bearer $OPENCRAWL_API_KEY"
```

OpenCrawl only claims cancellation while a run is still `queued`.

Once upstream extraction has started, the current provider route does not expose a verified cancellation contract. The API therefore returns `run_already_started` instead of falsely claiming the provider job stopped.

## Schema validation

If a JSON Schema is supplied, OpenCrawl validates the terminal structured result against the bounded schema subset used by this workflow:

- type
- required
- properties
- items
- enum

Validation does not fabricate missing values. A provider result can complete with `schema_valid=false`; the dataset preserves the actual returned structured data and the run exposes bounded validation errors.

## Datasets

Completed output is saved as operation `extract`.

Structured rows are stored in the generic `records` collection, while the full bounded extraction object is retained in the dataset output envelope. Existing JSON, JSONL and CSV exports work unchanged.

## Accounting

The quote reserves the maximum possible OpenCrawl wallet charge.

For asynchronous Firecrawl extraction, `maxCredits` is provider budget headroom, not measured consumption. OpenCrawl does **not** treat that launch budget as actual usage. Terminal `creditsUsed`, when reported by the provider, replaces that budget for measured settlement.

If a worker dies after a provider launch may have occurred but before the provider job ID was durably recorded, OpenCrawl fails closed and releases the user reservation instead of replaying the launch and risking duplicate provider work.

## Worker

The protected scheduler advances one durable capability run per tick:

```
GET /api/internal/capability-runs/tick
```

The endpoint accepts the same repository-scoped scheduler identity used by the existing monitor/crawl worker.

A newly created run is also targeted for one immediate launch attempt so users do not wait for the scheduler merely to start work.

## Limits

- 20 URLs per extraction.
- 4096 UTF-8 bytes per URL.
- 4000 characters for extraction instructions.
- 32 KB optional schema.
- 96 KB total request body.
- 1000 saved dataset rows.
- 2 MB saved dataset output.
- one hour durable run expiry.
- upstream identities and credentials remain server-side.
