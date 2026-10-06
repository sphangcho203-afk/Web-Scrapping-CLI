# Product price tracking

Open **Price Tracker** at `/dashboard/products`. An execution key attributes charges and spending limits. Review the single-page quote, confirm collection, then inspect and export the saved product rows. Enabling tracking requires a successful owned preview and explicit agreement to recurring charges.

The preview is a bounded native crawl, with public-target, peer-IP, redirect, robots and worker-lease controls preserved. It runs immediately when a lease is available. Lost responses can retry the same `Idempotency-Key`; subsequent polling retrieves the owned run without collecting again. The accepted `quote_revision` and `max_charge_credits` use the existing reservation rules.

## Source contract

Only published JSON-LD `Product` / `Offer` records are supported. Arrays and `@graph` offer references are supported. A record requires a name, unambiguous nonnegative decimal price, and a three-letter currency. Prices retain exact decimal strings and their original currency. Availability is optional; absent availability stays unknown. Every row carries a source URL, capture time, stable product/offer identity and `extraction_source=published_json_ld`.

There is no text-based guessing, currency conversion, JavaScript rendering, sign-in, or selection of aggregate price ranges. Conflicting offers, invalid metadata, metadata above 128 KB or 1500 nodes / 16 levels, and more than 32 offers fail closed. Missing prices produce an explicit failed preview with no product dataset and no customer charge.

## Schedule and change contract

`POST /api/product-trackers` accepts a successful preview `run_id`, `name`, `fields` (`price`, `availability`), `interval_minutes`, optional `max_charge_credits`, and `confirm_recurring=true`. The preview supplies the target, owned billing key and initial baseline. Enabling does not collect again or charge again. Concurrent identical enable requests return the same tracker; changed enable inputs return a conflict. Account monitor quotas still apply.

Schedules are approximate. Existing protected monitor ticks queue due product checks into the durable crawl queue; crawl ticks advance them. A tracker cannot overlap its own pending check. Each check obeys its saved credit ceiling and current account/key spending policies. Successful unchanged checks still cost credits. A blocked or unusable check has no customer charge and preserves the last good baseline.

Product checks compare sorted identities and selected fields; price comparisons include currency. Page text, capture time and formatting do not affect the fingerprint. Baselines and changes save product datasets. Unchanged checks save only monitor history. Changes preserve before/after values and prior/current dataset links when the previous dataset still exists. If it was deleted, change detection still uses the private hash, but prior values remain unknown.

Dataset insertion, outbox notification, baseline, monitor history, measured settlement and terminal transition are transactional. Paused, deleted, edited, superseded or revoked-key checks cannot publish stale output. Existing signed `dataset.saved` webhooks notify saved previews and changed snapshots; configure the receiver in Datasets. No email change-alert channel is added. Payment receipts retain the existing deduplication mechanism.

## API

- `POST /api/product-tracker/quote`: read-only review (`url`, optional owned `api_key_id`).
- `POST /api/product-tracker/runs`: confirmed preview, quote controls and `Idempotency-Key`.
- `GET /api/product-tracker/runs/{id}`: owned preview state and saved product rows.
- `POST /api/product-trackers`: enable a tracker from an owned completed preview.
- Existing `/api/monitors` APIs manage tracker history, edit, pause/resume and deletion.
- Existing dataset APIs retrieve and export the rows without another collection charge.

Read APIs accept the existing session or scoped API-key identity. Enabling requires execution permission; browser actions require a verified account. A foreign preview returns 404. Worker/scheduler endpoints retain their existing authorization.

## Payment recovery

Billing exposes **Check payment** for unfulfilled owned orders. `POST /api/billing/payments/{order_id}/reconcile` queries that existing Razorpay order's payments, validates captured status, exact amount, currency and order identity, then uses the locked transactional fulfillment method. It creates no purchase. Repeated requests and concurrent webhook delivery cannot grant credits twice.

Webhook journaling distinguishes lifecycle event type and signature validity. A `received` entry does not suppress a retry after provider or database failure. Capture fulfillment failures and unmatched capture orders remain retryable. Successful captured delivery is journaled as fulfilled. Production billing remains Supabase Vault-only and preview billing remains disabled by default.

## Verification limits

CI exercises mocked source/provider responses against real PostgreSQL and Chromium. This establishes workflow/accounting behavior, not extraction coverage on arbitrary merchant pages or actual external webhook delivery. Production authenticated tracking and receiver receipt require an authorized account/session and a configured receiver.
