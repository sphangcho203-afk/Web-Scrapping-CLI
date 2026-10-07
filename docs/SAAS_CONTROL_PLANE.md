# OpenCrawl v0.6 SaaS control plane

OpenCrawl v0.6 turns the capability fabric into a customer-facing MCP/API product with accounts, API keys, OAuth authorization, usage metering, credits, billing, monitors, and a web console.

## Canonical routes

All routes live on the same origin.

| Purpose | Path |
| --- | --- |
| Website | `/` |
| Pricing | `/pricing` |
| Documentation | `/docs` |
| Status | `/status` |
| Login | `/login` |
| Signup | `/signup` |
| Email verification | `/verify-email` |
| Dashboard | `/dashboard` |
| Permanent MCP | `/mcp` |
| OAuth protected-resource metadata | `/.well-known/oauth-protected-resource` |
| OAuth authorization-server metadata | `/.well-known/oauth-authorization-server` |
| OAuth authorization | `/oauth/authorize` |
| OAuth token exchange | `/oauth/token` |
| GitHub OAuth callback | `/api/auth/github/callback` |
| Razorpay webhook | `/api/webhooks/razorpay` |

The canonical permanent MCP URL is:

```text
https://opencrawl.top/mcp
```

A future custom domain can front the same app without changing the internal route layout.

The hosted endpoint uses stateless Streamable HTTP with JSON responses. An
unauthenticated request returns `401` with OAuth discovery metadata. After
authentication, clients use `POST` for initialization, notifications and tool
requests; a standalone SSE `GET` returns `405` with `Allow: POST` rather than
holding a serverless function open. This is not the legacy SSE transport.

For ChatGPT, select OAuth authentication and use dynamic client registration
without entering a static client secret. The authorization request may include
`offline_access` for refresh-token renewal. Resource scopes such as `mcp:read`
and `mcp:execute` must be granted by the OpenCrawl key used at consent;
`offline_access` does not add resource permissions to that key.

## Required production environment

### Control plane

```text
INTERNET_HANDS_CONTROL_POSTGRES_DSN=
INTERNET_HANDS_API_KEY=
```

`INTERNET_HANDS_CONTROL_POSTGRES_DSN` may point at the same Postgres cluster as the distributed fleet, but the control tables use their own `ih_*` namespace.

### GitHub login

```text
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
```

GitHub OAuth callback:

```text
https://opencrawl.top/api/auth/github/callback
```

A personal access token is not a replacement for the OAuth application's client ID/secret.

### Razorpay

```text
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=
```

Webhook URL:

```text
https://opencrawl.top/api/webhooks/razorpay
```

Fulfillment rules:

- prices are selected server-side from plan/credit-pack rows;
- checkout signatures are verified with `RAZORPAY_KEY_SECRET`;
- the server fetches the payment back from Razorpay;
- credits/subscriptions are fulfilled only for `captured` payments;
- order ID, amount, and currency must match the local payment order;
- webhook signatures are verified with `RAZORPAY_WEBHOOK_SECRET`;
- webhook events are idempotent.

### Password reset email

Optional Resend delivery:

```text
RESEND_API_KEY=
INTERNET_HANDS_FROM_EMAIL=
```

If email delivery is not configured, password-reset requests still return the same generic response and do not disclose whether an account exists.

## Authentication model

### Direct API key

```http
Authorization: Bearer ih_live_...
```

or

```http
X-API-Key: ih_live_...
```

Customer API keys are shown once; only SHA-256 hashes are persisted.

Email/password signup creates a provisional web session so the verification
screen can resend or confirm a code. Unverified accounts cannot create API
keys, monitors, billing orders, or OAuth grants. Password changes and password
resets revoke all existing web sessions.

### MCP OAuth

Unauthenticated MCP requests receive a `401` with a `WWW-Authenticate` challenge pointing at the protected-resource metadata document. OAuth-capable clients then use authorization-code + PKCE S256.

The authorization page validates an OpenCrawl API key, then issues a short-lived access token and rotating refresh token. The raw API key is not stored in OAuth token records.

## Metering

For customer-authenticated `tools/call` requests the gateway:

1. authenticates the API key or OAuth access token;
2. checks plan RPM;
3. quotes the underlying OpenCrawl work and applies the configured wallet burn multiplier;
4. checks whether the wallet can reserve that amount;
5. creates a request ID and reservation-backed usage event;
6. executes the MCP tool;
7. settles measured work, deducting monthly credits first and then purchased credits;
8. releases unused reservation headroom and records status, latency, output bytes, and final charge.

Operator calls using `INTERNET_HANDS_API_KEY` bypass customer charging.

## Plans

| Plan | INR/month | Credits | RPM | API keys | Monitors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Free | 0 | 250 | 10 | 1 | 1 |
| Builder | 499 | 25,000 | 60 | 5 | 10 |
| Pro | 1,499 | 150,000 | 240 | 20 | 50 |
| Scale | 4,999 | 750,000 | 600 | 100 | 250 |

Purchased credit packs use a separate rollover bucket.

All plans use the same tool catalog. Free, Builder, Pro, and Scale can call browser, sandbox, public, metered, and premium provider routes when the request is otherwise authorized/configured and the wallet can reserve the quoted charge. Plans differentiate included credits, RPM/concurrency, API-key limits, and monitor capacity rather than tool availability.

Hosted OpenCrawl work uses `OPENCRAWL_CREDIT_BURN_MULTIPLIER` (default `3`) after raw provider/work estimation. BYO connected apps and user-saved MCP servers remain zero OpenCrawl wallet charge for the external capability itself.

## Production rollout rule

Do not switch the Vercel production branch to v0.6 until:

- Ruff passes;
- pytest passes on Python 3.11, 3.12, and 3.13;
- the preview landing page and responsive console routes load;
- OAuth discovery documents load;
- unauthenticated `/mcp` returns the expected authorization challenge;
- signup, verification, login, session management, and API-key creation work
  against the configured control database;
- GitHub login completes against the production callback;
- Razorpay configuration reports ready without creating a live charge;
- webhook signature rejection/acceptance behavior is verified with non-financial test payloads.
