# Secrets policy

OpenCrawl production secrets are server-side configuration only.

Never commit or return values for:

- `RAZORPAY_KEY_SECRET`
- `RAZORPAY_WEBHOOK_SECRET`
- `GITHUB_CLIENT_SECRET`
- `RESEND_API_KEY`
- provider API keys and bearer tokens
- customer `ih_live_*` / `ih_test_*` API keys
- OAuth access/refresh tokens

Customer API keys are shown once and persisted only as hashes. OAuth access/refresh tokens are also persisted as hashes. Provider and billing credentials must never be included in MCP schemas, tool results, diagnostics, or browser-visible configuration payloads.

## Runtime secret storage

Platform integration rows may store non-secret configuration and a secret reference only.
Do not place raw provider credentials in `ih_platform_integrations.config`,
`ih_connections.secret_config`, diagnostics, or browser-visible payloads.

For production transactional email, store the Resend credential in Supabase Vault
and set `ih_platform_integrations.secret_name` to the Vault secret name. The
mailer may fall back to `RESEND_API_KEY` only for local development or emergency
recovery when database-backed configuration is unavailable.

