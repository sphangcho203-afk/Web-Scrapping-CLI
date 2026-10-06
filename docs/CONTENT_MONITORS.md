# Content-change monitors

Open **Monitors → Content changes**, enter a public page and select an owned API key with `mcp:execute`. The first successful check saves a readable-content baseline. Subsequent checks compare the title and extracted page text after collapsing whitespace. A change saves another dataset; unchanged checks retain history without creating another dataset or notification. HTML formatting, timestamps and source-body hashes do not determine content changes.

Create using the existing verified-session monitor API:

```json
{"name":"Pricing watch","type":"content","target":"https://example.com/pricing","interval_minutes":60,"config":{"api_key_id":"key_owned"}}
```

`POST /api/monitors/validate` and `POST /api/monitors` enforce the same contract. Configuration supports only `api_key_id`; this is a stored key ID, not the secret. Keys must belong to the account, remain active and allow execution. Existing plan monitor quotas apply. Intervals are 5–10,080 minutes. The first check is immediately due. Schedules are approximate: the existing protected monitor tick queues one due content check per invocation, and the independent crawl tick executes one job per invocation. Both production workflows run every five minutes; previews require an authorized manual tick. Health monitors continue using their existing executor.

## Execution and accounting

Each check uses the existing durable crawl queue, reservation, wallet ledger, worker lease and recovery mechanism. It captures one page, depth zero, with a 25-second total execution budget and at most 50,000 UTF-8 text bytes. Public-target and peer-IP validation, robots rules and redirect scope are enforced. Apex/`www` canonical redirects are allowed; unrelated hosts, port changes and HTTPS downgrades are rejected. The destination origin's robots rules are checked before its page is requested.

This release compares server-rendered text and title. It does not execute JavaScript or provide field/selector-specific pricing extraction. Empty, non-2xx, robots-blocked, failed or truncated captures are failed checks, preserve the last valid baseline and release the unused reservation. A successful baseline, unchanged comparison or detected change uses the existing measured `playground:crawl` charge and selected key attribution, bounded by its reservation. Usage arguments include the parent monitor ID. Repeated scheduler calls cannot create overlapping checks for a monitor; recovered workers cannot settle twice.

The monitor history reports `baseline`, `unchanged`, `changed`, `failed`, `blocked` or `cancelled`, actual credits, HTTP status and the durable job ID. Baselines and changes include a dataset link; changes also link to the prior capture. Configuring a dataset webhook enqueues the existing signed `dataset.saved` notification atomically for each saved baseline or change. Unchanged and failed checks enqueue no notification. The event remains a dataset notification; follow its dataset to inspect `monitor_id` and `monitor_status`.

Target, monitor type or billing-key changes reset the baseline and increment a configuration version. Renaming or changing the interval preserves it. Paused, deleted, superseded or unauthorized jobs are checked before network work and again at finalization. They release the unused reservation and cannot publish stale content. Pausing does not immediately interrupt an in-flight HTTP request. Monitor editing, baseline updates, dataset/outbox insertion, history, billing and terminal transitions use database locks and transactions.

Deleting a dataset clears its monitor/history/job links and associated pending notification. A private content fingerprint remains sufficient for subsequent comparisons; deleting a capture does not reset the monitor. Captured text remains only in saved datasets after a job finishes. History can contain a previous dataset ID whose capture has since been deleted.

## Verification and release gate

Isolated PostgreSQL tests exercise scheduling races, real wallet settlement, API ownership, key revocation, configuration fencing, saved baseline/change history, unchanged notification suppression, rollback after dataset insertion and deletion. Chromium verifies the billing-key form, capture links, escaping and mobile layout. Production promotion still requires a deployed authenticated create → scheduled check → dataset/history → unchanged/change sequence, including an external notification receipt if configured. Local fixtures and passing CI do not establish production verification.
