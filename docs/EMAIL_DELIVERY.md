# OpenCrawl transactional email

OpenCrawl can load mail configuration from the control database while keeping
provider credentials out of Vercel environment variables.

## Production layout

- `ih_platform_integrations` stores non-secret configuration.
- `secret_name` points to a Supabase Vault secret.
- `mailer.py` reads the database first and falls back to environment variables
  only when the database configuration is absent or unavailable.
- A disabled database integration is authoritative and prevents environment
  fallback from silently re-enabling mail.

## Resend configuration

Create the Resend secret in Supabase Vault:

```sql
select vault.create_secret(
  '<RESEND_API_KEY>',
  'opencrawl_resend_api_key',
  'OpenCrawl production Resend API key'
);
```

Then configure transactional email:

```sql
insert into ih_platform_integrations (
  key,
  provider,
  config,
  secret_name,
  enabled
)
values (
  'transactional_email',
  'resend',
  '{
    "from_name": "OpenCrawl",
    "default_from_email": "notifications@opencrawl.top",
    "reply_to_email": "support@opencrawl.top",
    "senders": {
      "auth": "auth@opencrawl.top",
      "billing": "billing@opencrawl.top",
      "security": "security@opencrawl.top",
      "notifications": "notifications@opencrawl.top"
    }
  }'::jsonb,
  'opencrawl_resend_api_key',
  true
)
on conflict (key) do update set
  provider = excluded.provider,
  config = excluded.config,
  secret_name = excluded.secret_name,
  enabled = excluded.enabled,
  updated_at = now();
```

The `senders` map is optional. Existing mail call sites continue using the
default sender. Callers that need a specific identity can pass a `sender_key`
such as `auth`, `billing`, or `security`.

## Environment fallback

Existing `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, SMTP variables, and
`MAIL_PROVIDER` remain supported for local development and emergency recovery.
They are no longer required for normal production operation once the database
row and Vault secret exist.

## Safe diagnostics

`mail_settings_snapshot()` reports which source and provider are active and
whether a credential is configured. It never returns the credential value.
