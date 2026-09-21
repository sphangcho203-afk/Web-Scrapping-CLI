# Internet Hands account security

Internet Hands v0.7 includes transactional email, email verification, phone ownership verification, login notifications, payment confirmations, and optional TOTP two-factor authentication.

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

## Phone ownership verification

Phone verification proves that the signed-in user controls a submitted phone number. Internet Hands does **not** expose a reverse-subscriber lookup or a "person behind the SIM" feature.

Numbers are parsed and normalized locally with libphonenumber metadata before an external OTP is attempted. The provider layer currently supports Twilio Verify v2 and Vonage Verify v2, with provider order controlled by:

```text
PHONE_VERIFY_PROVIDERS=twilio,vonage
```

Twilio configuration:

```text
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
# or TWILIO_API_KEY / TWILIO_API_SECRET
TWILIO_VERIFY_SERVICE_SID=
TWILIO_LOOKUP_SIM_SWAP=0
```

Vonage fallback configuration:

```text
VONAGE_API_KEY=
VONAGE_API_SECRET=
VONAGE_VERIFY_BRAND=Internet Hands
VONAGE_VERIFY_VOICE_FALLBACK=1
VONAGE_VERIFY_FRAUD_CHECK=0
```

The default flow is:

1. normalize and validate the number;
2. select the first configured verification provider;
3. send an OTP by SMS or voice (WhatsApp is available with Twilio);
4. persist only the provider request ID and verification state;
5. confirm the user-entered code with the same provider;
6. mark the number verified only after provider approval;
7. optionally enrich the **verified account owner's own number** with carrier, line-type and eligible SIM-swap anti-fraud data.

Automatic provider failover stops once an OTP send is attempted because retrying a second provider can create duplicate messages when the first provider's outcome is ambiguous.

Phone endpoints:

```text
GET    /api/auth/phone/providers
GET    /api/auth/phone/status
POST   /api/auth/phone/start
POST   /api/auth/phone/confirm
POST   /api/auth/phone/intelligence
DELETE /api/auth/phone
```

Resends are rate-limited, pending verifications expire, incorrect-code attempts are bounded, and a verified phone number cannot be attached to two Internet Hands accounts at the same time.

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
