# OpenCrawl transactional email

OpenCrawl can load mail configuration from the control database while keeping
provider credentials out of Vercel environment variables.

## Production layout

- Neon remains the authoritative OpenCrawl control/application database.
- `ih_platform_integrations` stores non-secret configuration in the control DB.
- `secret_name` points to a Supabase Vault secret.
- `mailer.py` resolves that secret through a service-role-only Supabase RPC,
  using the already-configured `SUPABASE_URL` and
  `SUPABASE_SERVICE_ROLE_KEY`.
- Environment mail variables are used only when database/Vault configuration is
  absent or temporarily unavailable.
- A disabled database integration is authoritative and prevents environment
  fallback from silently re-enabling mail.

## Resend configuration

Create the service-role-only Vault RPC once in the OpenCrawl Supabase project:

```sql
create or replace function public.open_crawl_get_vault_secret(p_secret_name text)
returns text
language sql
security definer
set search_path = ''
as $
  select decrypted_secret
  from vault.decrypted_secrets
  where name = p_secret_name
  order by updated_at desc nulls last, created_at desc
  limit 1;
$;

revoke all on function public.open_crawl_get_vault_secret(text)
  from public, anon, authenticated;
grant execute on function public.open_crawl_get_vault_secret(text)
  to service_role;
```

Create the Resend secret in Supabase Vault:

```sql
select vault.create_secret(
  '<RESEND_API_KEY>',
  'opencrawl_resend_api_key',
  'OpenCrawl production Resend API key'
);
```

Then configure transactional email in the Neon control database:

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
