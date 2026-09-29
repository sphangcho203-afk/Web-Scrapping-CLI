# Saved Playground datasets

Search, research and crawl runs now save their collected output in the control database. A successful response includes `dataset.id`; open **Datasets** in the console to inspect it later. Downloading a saved result does not execute the collection again and incurs no additional collection charge.

## What is saved

Each row preserves a source record and a `record_type`: `search_results`, `pages`, or `evidence`. Search rows contain the discovered title, URL and description when supplied by the source. Research evidence includes captured text and failure details. Playground URL crawls include bounded readable text, title, description, headings, capture timestamp, status, depth and source hashes. Check `content_truncated` and `content_error` before using a page. See [crawl content](CRAWL_CONTENT.md) for extraction limits and a RAG export example. The complete result envelope, including synthesis and provenance, is retained internally in `output`.

One dataset is associated with each saved Playground request. Saving again for the same request returns the original dataset. This prevents duplicate storage; it does not provide idempotent execution for repeated POST requests. A new collection request still has a new request ID and charge. API keys and request credentials are never copied into datasets.

## First run

Create an account, verify email, create an API key with `mcp:read` and `mcp:execute`, and fund the wallet if necessary. Set the origin to your actual deployment and keep the key in an environment variable.

```bash
export OPENCRAWL_ORIGIN="https://your-opencrawl-domain"
export OPENCRAWL_API_KEY="your-api-key"
curl --fail-with-body "$OPENCRAWL_ORIGIN/api/playground/run" \
  -H "Authorization: Bearer $OPENCRAWL_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"operation":"search","query":"public API documentation","max_pages":5}'
```

The response contains the existing `request_id`, `usage`, `summary`, and `result` fields, plus dataset metadata. Save its ID. The underlying search/crawl costs follow the existing wallet rules and are available in Usage. All plans can retrieve their own saved outputs; a wallet balance is not required to read a previously collected result.

## API reference

| Method | Endpoint | Behavior |
|---|---|---|
| GET | `/api/datasets?limit=25&offset=0` | List account-owned metadata, newest first; maximum limit 100 |
| GET | `/api/datasets/{id}?limit=50&offset=0&q=price` | Paginated rows and columns; case-insensitive text filter; maximum limit 100 |
| GET | `/api/datasets/{id}/export?format=json` | Download all rows; formats `json`, `jsonl`, `csv`; filters and pagination do not affect export |
| PATCH | `/api/datasets/{id}` | Rename with JSON body `{"name":"Saved pricing sources"}`; 1–120 characters |
| DELETE | `/api/datasets/{id}` | Delete output; usage history and original charge remain |

Read operations require `mcp:read` or `*`. Rename/delete require `mcp:execute` or `*`. An authenticated console session also works. An invalid supplied key is rejected even if a browser session exists. Records belonging to another account return 404. URLs never contain credentials.

```bash
export OPENCRAWL_DATASET_ID="ds_id_from_response"
curl --fail-with-body "$OPENCRAWL_ORIGIN/api/datasets/$OPENCRAWL_DATASET_ID?limit=50" \
  -H "Authorization: Bearer $OPENCRAWL_API_KEY"
curl --fail-with-body "$OPENCRAWL_ORIGIN/api/datasets/$OPENCRAWL_DATASET_ID/export?format=csv" \
  -H "Authorization: Bearer $OPENCRAWL_API_KEY" -o results.csv
```

JavaScript (Node 18+):

```javascript
const origin = process.env.OPENCRAWL_ORIGIN;
const id = process.env.OPENCRAWL_DATASET_ID;
const headers = { Authorization: `Bearer ${process.env.OPENCRAWL_API_KEY}` };
const response = await fetch(`${origin}/api/datasets/${encodeURIComponent(id)}?limit=100`, { headers });
if (!response.ok) throw new Error(await response.text());
const { dataset, rows, total } = await response.json();
console.log(dataset.name, rows, total);
```

Python:

```python
import os
import httpx

origin = os.environ["OPENCRAWL_ORIGIN"].rstrip("/")
dataset_id = os.environ["OPENCRAWL_DATASET_ID"]
response = httpx.get(
    f"{origin}/api/datasets/{dataset_id}/export",
    params={"format": "jsonl"},
    headers={"Authorization": f"Bearer {os.environ['OPENCRAWL_API_KEY']}"},
    timeout=30,
)
response.raise_for_status()
with open("results.jsonl", "w", encoding="utf-8") as output:
    output.write(response.text)
```

## Output and failure behavior

The saved envelope is limited to 2 MB and 1000 rows. Oversized output is not silently truncated: the collection response retains the live result, sets `dataset: null`, and includes `warnings[].code = dataset_not_saved`. Database failures follow the same explicit behavior. Copy the raw JSON before leaving the page. Collection still consumed resources, so its original charge applies. There is no automatic retry of collection or storage in this tranche.

CSV serializes nested objects and arrays as JSON cells. Text beginning with spreadsheet formula characters is prefixed with an apostrophe, including when preceded by whitespace. Numeric negative values remain numeric. JSON and JSONL preserve the source values. Empty collections produce a saved dataset with zero rows.

Names and values are escaped in the browser; downloads have a server-generated filename, `no-store` cache policy, and `nosniff` header. Saved output is private to its account. It remains until explicitly deleted, account deletion, or deletion of its linked usage event; there is no new time-based retention scheduler.

## Deployment

`ih_datasets` and its owner/time index are additive statements in `ControlStore.ensure_schema()`, matching the repository's existing migration mechanism. They use the selected control database, whether Neon or Supabase. No data is moved between databases. Deploy the backend and web bundle together. On the first dataset read/write in a fresh process, schema initialization ensures the table exists. Verify a real authenticated collection, list, export, rename and delete in preview before promotion.

## Next work

Dataset delivery via webhooks, monitor appends, recipes and durable asynchronous jobs remain separate implementation waves. Existing outputs from before this change cannot be reconstructed from usage metadata alone.
