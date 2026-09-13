# Internet Hands v0.6 SaaS control plane

Internet Hands v0.6 turns the capability fabric into a customer-facing MCP/API product with accounts, API keys, OAuth authorization, usage metering, credits, billing, monitors, and a web console.

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
| Dashboard | `/dashboard` |
| Permanent MCP | `/mcp` |
| OAuth protected-resource metadata | `/.well-known/oauth-protected-resource` |
| OAuth authorization-server metadata | `/.well-known/oauth-authorization-server` |
| OAuth authorization | `/oauth/authorize` |
| OAuth token exchange | `/oauth/token` |
| GitHub OAuth callback | `/api/auth/github/callback` |
| Razorpay webhook | `/api/webhooks/razorpay` |

With the current Vercel production alias the permanent MCP URL is intended to be:

```text
https://web-scrapping-cli.vercel.app/mcp
```

A future custom domain can front the same app without changing the internal route layout.

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
https://web-scrapping-cli.vercel.app/api/auth/github/callback
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
https://web-scrapping-cli.vercel.app/api/webhooks/razorpay
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

### MCP OAuth

Unauthenticated MCP requests receive a `401` with a `WWW-Authenticate` challenge pointing at the protected-resource metadata document. OAuth-capable clients then use authorization-code + PKCE S256.

The authorization page validates an Internet Hands API key, then issues a short-lived access token and rotating refresh token. The raw API key is not stored in OAuth token records.

## Metering

For customer-authenticated `tools/call` requests the gateway:

1. authenticates the API key or OAuth access token;
2. checks plan RPM;
3. determines the tool cost;
4. checks the wallet;
5. deducts monthly credits first, then purchased credits;
6. creates a request ID and usage event;
7. executes the MCP tool;
8. records status, latency, and output bytes.

Operator calls using `INTERNET_HANDS_API_KEY` bypass customer charging.

## Plans

| Plan | INR/month | Credits | RPM | API keys | Monitors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Free | 0 | 2,500 | 10 | 1 | 1 |
| Builder | 499 | 25,000 | 60 | 5 | 10 |
| Pro | 1,499 | 150,000 | 240 | 20 | 50 |
| Scale | 4,999 | 750,000 | 600 | 100 | 250 |

Purchased credit packs use a separate rollover bucket.

## Production rollout rule

Do not switch the Vercel production branch to v0.6 until:

- Ruff passes;
- pytest passes on Python 3.11, 3.12, and 3.13;
- the preview landing page loads;
- OAuth discovery documents load;
- unauthenticated `/mcp` returns the expected authorization challenge;
- signup/login/API-key creation work against the configured control database;
- GitHub login completes against the production callback;
- Razorpay configuration reports ready without creating a live charge;
- webhook signature rejection/acceptance behavior is verified with non-financial test payloads.
