# Readable crawl content

Playground URL crawls now extract readable content from each existing HTTP capture and save it in the run's dataset. Extraction does not issue another request. Existing public-target validation, redirect checks, robots policy, traversal limits and wallet accounting still apply.

```json
{"operation":"crawl","url":"https://example.com/docs/","max_pages":10,"include_content":true,"max_content_bytes_per_page":50000,"max_content_bytes":750000}
```

POST this body to `/api/playground/run` with an API key with `mcp:execute`. The returned `dataset.id` identifies the saved output. Use `mcp:read` for subsequent retrieval and exports. See [Datasets](DATASETS.md) for authentication and lifecycle examples.

| Control | Playground default | Allowed values |
|---|---|---|
| `include_content` | `true` | Boolean; `false` returns metadata only |
| `max_content_bytes_per_page` | 50,000 | 1–200,000 bytes |
| `max_content_bytes` | 750,000 | 1–1,000,000 bytes across the crawl |

The byte budgets apply to UTF-8 page text. Limits never split a Unicode character. Pages completing first receive the remaining aggregate allowance; concurrent requests can therefore change which page is shortened. Page title is separately limited to 1,000 bytes, description to 2,000 bytes, and headings to 40 entries of 500 bytes each. `content_truncated` is true when text or these metadata fields are shortened. Each page includes `captured_at` and the existing source `sha256`; the hash describes the fetched source, not the extracted or shortened text. Result and summary `content_bytes` count only returned UTF-8 text bytes. Their `content_truncated` flags indicate whether any page content was shortened. The existing `truncated` flag describes crawl traversal and is independent.

HTML extraction removes script and style content and returns normalized readable text. Successful text, HTML, JSON and XML captures support extraction. Non-2xx responses, unsupported binary media, empty captures and extraction failures carry `content_error`; the fetch status and provenance remain available. Robots-blocked and failed fetches retain their existing `error` and have no page text. This path does not execute JavaScript, capture screenshots, preserve raw HTML or guarantee article-only text. Earlier saved datasets retain their original fields.

The Python `crawl()` interface defaults to `include_content=False` to preserve existing CLI and provider behavior. Content collection must be requested explicitly by those callers. Playground enables it by default for URL crawls; query-only research keeps its existing evidence extraction behavior.

## Use JSONL for a RAG pipeline

Download `/api/datasets/{id}/export?format=jsonl`, then select readable page rows. Keep source metadata with each chunk. A shortened page may still be useful, but decide whether to accept it or collect again with a larger budget. Downloading an existing dataset has no collection charge; a new collection is metered.

```python
import json

with open("results.jsonl", encoding="utf-8") as source:
    for line in source:
        page = json.loads(line)
        if page["record_type"] != "pages" or not page.get("text") or page.get("content_error"):
            continue
        document = {
            "text": page["text"],
            "metadata": {key: page.get(key) for key in
                         ("url", "title", "captured_at", "sha256", "content_truncated")},
        }
        # Pass document to your own chunker and embedding pipeline.
        print(document["metadata"])
```

Dataset storage retains its existing 2 MB envelope and 1,000 row limits. Text budgets do not guarantee that every mixed search/research result fits that envelope. An oversized or failed save returns `dataset: null` with `dataset_not_saved`; the live collection and its original charge remain. Inspect the response before relying on durable output.
