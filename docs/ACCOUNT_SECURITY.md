# Internet Hands account security

Internet Hands v0.7 includes transactional email, email verification, login notifications, payment confirmations, and optional TOTP two-factor authentication.

## Transactional email

Resend is the preferred production mail transport; SMTP remains a configurable fallback. Configure these server-side variables in both Vercel Production and Preview when testing previews:

```text
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM_EMAIL=noreply@example.com
SMTP_FROM_NAME=Internet Hands
SMTP_STARTTLS=true
SMTP_USE_SSL=false
```

For port 465, use `SMTP_USE_SSL=true` and normally `SMTP_STARTTLS=false`.

If SMTP is not configured, the existing Resend variables can be used as a fallback:

```text
RESEND_API_KEY=...
INTERNET_HANDS_FROM_EMAIL=noreply@example.com
```

No SMTP password or provider API key is exposed to the browser, MCP clients, account APIs, or email event records.

## Email verification

Email/password signup creates an unverified account and sends both:

- a verification link;
- a six-digit code valid for 15 minutes.

GitHub-created accounts also require an Internet Hands verification step even when GitHub reports the upstream address as verified. Existing already-verified Internet Hands accounts keep their verification state when GitHub is linked.

Verification endpoints:

```text
GET  /api/auth/verification/status
POST /api/auth/email-verification/send
POST /api/auth/email-verification/confirm
GET  /api/auth/verify-email?token=...
```

Signup returns a provisional web session and sends the user to `/verify-email`.
Password and GitHub login do the same for any account that is still pending.
Creating API keys, monitors, billing orders, and OAuth grants is blocked until
the Internet Hands email is verified.

## Transactional messages

The mail layer covers:

- signup/email verification;
- account-verification confirmation;
- successful password sign-ins;
- successful GitHub sign-ins;
- password reset;
- Razorpay captured-payment confirmation;
- TOTP 2FA enabled/disabled security notices.

Payment emails are deduplicated by payment/order identity so the checkout verification path and Razorpay webhook cannot send duplicate confirmations.

## TOTP 2FA

TOTP is optional and RFC 6238-compatible (SHA-1, six digits, 30-second period). It works with standard authenticator apps.

Required server-side encryption variable:

```text
INTERNET_HANDS_ENCRYPTION_KEY=<long random secret>
```

`INTERNET_HANDS_OAUTH_SIGNING_SECRET` is accepted as a migration fallback, but a dedicated encryption key is preferred.

TOTP secrets are encrypted at rest with Fernet using key material derived from the server encryption secret. Recovery codes are stored only as SHA-256 hashes.

Security endpoints:

```text
GET  /api/auth/2fa/status
POST /api/auth/2fa/setup
POST /api/auth/2fa/confirm
POST /api/auth/2fa/challenge
POST /api/auth/2fa/disable
POST /api/auth/2fa/recovery/regenerate
GET  /api/security/status
```

When 2FA is enabled, password and GitHub sign-in stop before session creation and require a TOTP or one-time recovery code. TOTP counters are recorded to reject replay of an already-used time step.

Recovery codes are shown only when generated or regenerated. Users should store them outside the Internet Hands account.

## Account and session management

The web console uses these authenticated endpoints for account security:

```text
PATCH /api/account/profile
GET   /api/account/sessions
POST  /api/account/sessions/{session_id}/revoke
POST  /api/account/sessions/revoke-all
POST  /api/account/password
```

Changing a password or completing a password reset revokes every existing web
session. A successful password change also sends a security notification.

`GET /api/security/status` reports only user-facing capability state. It does
not expose the configured mail provider, encryption secrets, or infrastructure
details.
