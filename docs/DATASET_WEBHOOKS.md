# Saved dataset webhook delivery

Use webhook delivery when an automation should react to collected output without polling. Set one receiver per account in **Datasets → Webhook delivery**, then collect in Playground. A successfully saved new dataset creates a `dataset.saved` event in the same database transaction. Re-saving the same request does not create another event. Earlier datasets, failed saves, and collections made while the endpoint is disabled do not create notifications.

The event contains the dataset ID, request ID, operation, row count and relative API path. It contains no collected page bodies or account API credentials. Your receiver uses its own OpenCrawl read key to download JSON, JSONL or CSV. The signing secret authenticates notifications; it does not authorize dataset downloads.

## Configure a receiver

Read endpoints accept a verified console session or API key with `mcp:read`; configuration, removal and retry require `mcp:execute`. Normal account isolation applies. Configure a public HTTPS URL on port 443. Credentials in URL authority, fragments and private IPs are rejected. DNS names are checked at delivery, and the connection is pinned to a validated public IP. Redirects are never followed. Put receiver authentication in signature verification rather than embedding credentials in the URL.

```bash
export OPENCRAWL_ORIGIN="https://your-opencrawl-domain"
export OPENCRAWL_API_KEY="your-api-key"
curl --fail-with-body "$OPENCRAWL_ORIGIN/api/dataset-webhook" \
  -X PUT -H "Authorization: Bearer $OPENCRAWL_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://your-app.example/webhooks/opencrawl","enabled":true}'
```

The response includes `endpoint` and a one-time `signing_secret` on creation, URL change or rotation. Save the secret securely in your receiver, then collect data. GET settings never returns the secret or its ciphertext. Responses are `no-store`. Ordinary saves and pause/resume preserve the secret. To rotate, PUT the same URL with `rotate_secret:true`. Changing the URL automatically rotates it. Queued events use the current endpoint and current secret when claimed; already claimed events can still use the prior configuration.

Example notification:

```json
{"id":"wh_event_id","type":"dataset.saved","version":1,"created_at":"2026-09-30T00:00:00+00:00","data":{"dataset_id":"ds_id","request_id":"req_id","operation":"crawl","row_count":10,"path":"/api/datasets/ds_id"}}
```

## Verify signatures and deduplicate

Headers are `X-OpenCrawl-Event: dataset.saved`, `X-OpenCrawl-Delivery: wh_event_id`, and `X-OpenCrawl-Signature: t=UNIX_SECONDS,v1=HEX_DIGEST`. The digest is HMAC-SHA256 over the timestamp's ASCII decimal representation, a literal period, and the exact raw UTF-8 body bytes. Use the signing secret's UTF-8 bytes as the HMAC key. Each attempt has a fresh timestamp/signature, but the event ID and stored body remain the same.

Read raw bytes before JSON parsing. Reject timestamps outside your clock-skew tolerance and compare signatures in constant time. Deduplicate the event ID in durable storage before applying work; a process restart or lost acknowledgment can produce duplicates. Return 2xx only after you have durably accepted the event. Defer expensive processing to your own queue.

Python verification helper:

```python
import hashlib
import hmac
import time


def verify(raw_body: bytes, signature: str, signing_secret: str) -> bool:
    try:
        fields = dict(part.split("=", 1) for part in signature.split(","))
        timestamp = int(fields["t"])
        supplied = fields["v1"]
    except (ValueError, KeyError):
        return False
    if abs(time.time() - timestamp) > 300:
        return False
    expected = hmac.new(signing_secret.encode(),
                        str(timestamp).encode() + b"." + raw_body,
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)
```

After verification, parse JSON, check type/version, and ensure the body ID matches `X-OpenCrawl-Delivery`. Use a durable unique key on that ID. Do not fetch an arbitrary URL from the payload: construct the export URL from your configured OpenCrawl origin and the `dataset_id`.

For n8n, Make or a custom worker, first deploy a receiver that performs raw-body verification and durable deduplication, then pass the accepted event into the workflow. Download `/api/datasets/{id}/export?format=jsonl` with a separately stored read key to drive a RAG pipeline, spreadsheet import or downstream analysis. A basic webhook trigger alone does not establish signature verification.

## Delivery and recovery

The existing GitHub scheduler invokes the protected `/api/internal/dataset-webhooks/tick` entrypoint. Each tick claims at most five events using database locks and a 60-second lease, then makes one bounded five-second attempt per event. Expired leases are reclaimed after crashes. The configured production workflow requests a tick every five minutes; actual timing depends on GitHub scheduling and endpoint availability. Preview does not receive scheduled production ticks automatically.

A 2xx response marks delivery complete. Network errors, timeouts, transient DNS failure, 408, 429 and 5xx schedule another attempt. Other 4xx, redirects and public-target policy failures end the retry cycle immediately. There are at most five automatic attempts per cycle. Minimum backoff after failures is 60, 300, 1,500 and 3,600 seconds; the next scheduler tick can add delay. Receiver bodies are not read or stored, and errors omit receiver URLs and credentials.

| Endpoint | Purpose |
|---|---|
| GET `/api/dataset-webhook` | Read current receiver settings and setup availability |
| PUT `/api/dataset-webhook` | Set URL, `enabled` boolean and optional `rotate_secret` boolean |
| DELETE `/api/dataset-webhook` | Remove configuration, queued events and delivery history; datasets remain |
| GET `/api/dataset-webhook/deliveries?limit=25&offset=0` | Paginated owned delivery history; maximum limit 100 |
| POST `/api/dataset-webhook/deliveries/{id}/retry` | Requeue a failed, unexpired delivery with an enabled endpoint |

Retry resets the attempt counter while preserving the event ID and body. Delivered, pending and active events cannot be manually requeued. Foreign IDs return 404. An incompatible state returns 409. Disable delivery to hold existing queued events; re-enable to resume them. New datasets created while disabled have no event. Removing the endpoint or dataset removes associated events. An HTTP request already in flight may still complete after pause, rotation or removal.

Delivery records expire 30 days after creation and are pruned by the dispatcher, including paused/failed backlog. Their datasets retain the existing dataset lifecycle. No notification storage history is guaranteed if scheduler ticks stop. This implementation adds no webhook delivery charge; the original collection is metered as before. It delivers saved Playground completion events, not monitor changes or asynchronous job progress.

## Deployment and verification

The additive `ih_dataset_webhook_endpoints` and `ih_dataset_webhook_deliveries` tables use the existing control database. Secret storage reuses `INTERNET_HANDS_ENCRYPTION_KEY`; setup reports unavailable if this deployment lacks a valid key. Keep the encryption key stable. Deploy backend, browser bundle and scheduler workflow together. The dispatcher accepts the existing scheduler OIDC identity or configured `CRON_SECRET`, not ordinary account API keys.

Before production promotion, configure a receiver you control in preview, store its secret, perform an authenticated collection, invoke a preview tick with authorized scheduler credentials, verify the signature and download the dataset, then induce an error and verify retry/history. No real external receiver was configured or contacted during development.

Design references: [GitHub webhook best practices](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks), [GitHub signature validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries), and [HTTPCore SNI extension](https://www.encode.io/httpcore/extensions/). OpenCrawl's event shape and retry policy above are its own contract.
