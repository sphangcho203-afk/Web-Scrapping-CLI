# Secrets policy

Internet Hands production secrets are server-side configuration only.

Never commit or return values for:

- `RAZORPAY_KEY_SECRET`
- `RAZORPAY_WEBHOOK_SECRET`
- `GITHUB_CLIENT_SECRET`
- `RESEND_API_KEY`
- provider API keys and bearer tokens
- customer `ih_live_*` / `ih_test_*` API keys
- OAuth access/refresh tokens

Customer API keys are shown once and persisted only as hashes. OAuth access/refresh tokens are also persisted as hashes. Provider and billing credentials must never be included in MCP schemas, tool results, diagnostics, or browser-visible configuration payloads.
