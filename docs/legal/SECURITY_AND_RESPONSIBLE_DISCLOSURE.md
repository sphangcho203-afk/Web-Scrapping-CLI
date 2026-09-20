# Security & Responsible Disclosure

**Policy version:** 2026-09-20  
**Effective date:** 20 September 2026  
**Last updated:** 20 September 2026

Security controls used by Internet Hands, shared-responsibility expectations, and rules for reporting vulnerabilities safely.

## 1. Security model

- Passwords are stored as password hashes rather than plaintext passwords.
- Customer API keys are shown once and persisted as hashes.
- OAuth and provider secrets are intended to remain server-side and out of browser-visible configuration.
- TOTP secrets are encrypted at rest when two-factor authentication is enabled; recovery codes are stored as hashes.
- Web sessions use HTTP-only cookies, and privileged product actions require a verified account.
- OAuth flows use scoped authorization controls and PKCE where supported by the Internet Hands authorization flow.
- Billing fulfillment is verified server-side against captured payment state and the locally created order.
- Usage and request ledgers retain request identifiers and execution metadata for audit and troubleshooting.

## 2. Shared responsibility

You are responsible for the security of devices, email accounts, API keys, recovery codes, connected services, and environments you control. Use two-factor authentication where available, use least-privilege scopes, rotate exposed credentials, and revoke sessions you no longer recognize.

## 3. Reporting a vulnerability

Use the private vulnerability-reporting or security contact method published in the official Internet Hands repository. Include the affected component, impact, reproduction conditions, and enough evidence to validate the issue without including unnecessary personal data or third-party secrets.

> **Please report privately:** Do not publish an unpatched vulnerability, access another user's data to prove impact, retain copied secrets, or create unnecessary persistence.

## 4. Good-faith research

If you act in good faith, stay within systems and accounts you are authorized to test, avoid privacy violations and service disruption, and follow this policy, we will treat your research as authorized to the extent we can. This does not authorize testing of third-party providers or customer systems outside their own published rules.

## 5. Response

We aim to validate credible reports, reduce immediate risk, develop a fix, and coordinate disclosure reasonably. Response time depends on severity, reproducibility, provider dependencies, and operational complexity.

## 6. No absolute-security promise

Security controls reduce risk but cannot eliminate it. Keep your own backups and incident plans for workflows where availability, confidentiality, or integrity is important.

---

Hosted version: `/legal` and the matching `/legal/<policy>` route.