# Internet Hands Legal & Privacy Documentation

**Policy version:** 2026-09-20  
**Effective date:** 20 September 2026  
**Last updated:** 20 September 2026

This directory contains the human-readable legal and privacy documents for the hosted **Internet Hands** service.

The public website renders the same policy set through the **Legal Center** at `/legal`. The browser-facing source of truth for this version is `web/legal-content.js`; these Markdown files are maintained as reviewable repository copies so policy changes can be inspected in normal Git history.

## What these files cover

| File | Purpose |
| --- | --- |
| [PRIVACY_POLICY.md](./PRIVACY_POLICY.md) | Explains what personal information Internet Hands processes, why it is used, who may receive it, retention, security, user choices, and privacy rights. |
| [DATA_PROCESSING_AND_RETENTION.md](./DATA_PROCESSING_AND_RETENTION.md) | Explains customer-directed data processing, retention, deletion, subprocessors, incidents, and business data-processing responsibilities. |
| [COOKIE_AND_LOCAL_STORAGE_NOTICE.md](./COOKIE_AND_LOCAL_STORAGE_NOTICE.md) | Describes the authentication/security cookies and browser storage currently used by the product and clarifies that the first-party app does not use behavioral advertising cookies. |
| [THIRD_PARTY_SERVICES_AND_SUBPROCESSORS.md](./THIRD_PARTY_SERVICES_AND_SUBPROCESSORS.md) | Lists the categories of external providers Internet Hands may rely on for hosting, databases, payments, email, authentication, web data, connected apps, and execution. |
| [TERMS_OF_SERVICE.md](./TERMS_OF_SERVICE.md) | Defines the contract for use of the hosted Service, including accounts, connected services, automation, billing, IP, suspension, disclaimers, and liability. |
| [ACCEPTABLE_USE_POLICY.md](./ACCEPTABLE_USE_POLICY.md) | Defines prohibited uses such as unauthorized access, credential abuse, malware, phishing, unlawful surveillance, spam, infringement, and resource abuse. |
| [BILLING_CREDITS_AND_REFUNDS.md](./BILLING_CREDITS_AND_REFUNDS.md) | Explains plans, metered credits, captured-payment verification, renewals, cancellations, refunds, chargebacks, taxes, and pricing changes. |
| [SECURITY_AND_RESPONSIBLE_DISCLOSURE.md](./SECURITY_AND_RESPONSIBLE_DISCLOSURE.md) | Documents security controls, shared responsibility, vulnerability reporting, and good-faith security research expectations. |
| [COPYRIGHT_AND_TAKEDOWN_POLICY.md](./COPYRIGHT_AND_TAKEDOWN_POLICY.md) | Explains third-party content ownership and the process for good-faith copyright or content-removal requests. |

## Privacy architecture in plain English

Internet Hands is an execution layer. It may process account information, authentication/security records, usage metadata, payment references, monitor configuration, and the content a user explicitly asks the Service to fetch, transform, monitor, or send to another connected tool.

The privacy documentation is deliberately split into several files because they answer different questions:

1. **Privacy Policy** — what data is processed and why.
2. **Data Processing & Retention** — how customer-directed data is handled over its lifecycle.
3. **Cookie Notice** — what the browser stores locally or in cookies.
4. **Third-Party Services & Subprocessors** — where data may go when infrastructure or a user-requested integration requires an external provider.
5. **Security & Responsible Disclosure** — the controls used to reduce risk and how vulnerabilities should be reported.

These documents should be read together rather than treating the Privacy Policy as the entire privacy model.

## Implementation-aligned statements

The current policy set is written to match the actual product behavior, including:

- password hashing rather than plaintext password storage;
- hashed customer API keys;
- server-side provider and OAuth secrets;
- encrypted TOTP secrets and hashed recovery codes;
- HTTP-only authenticated web sessions;
- email verification before privileged product actions;
- request and usage ledgers;
- Razorpay payment verification before paid capacity is fulfilled;
- transactional email through configured providers;
- user-directed routing to APIs, remote MCP servers, browser/sandbox systems, search providers, and connected applications.

If the implementation changes, the policy text must change with it.

## Update checklist

Review and version these documents whenever any of the following changes:

- a new category of personal data is collected;
- a new provider or subprocessor receives user data;
- payment or subscription behavior changes;
- cookies, analytics, advertising, or browser storage behavior changes;
- retention or deletion behavior changes;
- authentication/security architecture changes;
- new high-impact automation capabilities are added;
- the legal operator, governing law, support channel, or business identity changes;
- a new country or regulated customer segment is actively served.

For a material policy change:

1. Update `web/legal-content.js`.
2. Update the matching Markdown file(s) in this directory.
3. Change the policy version and effective date.
4. Verify footer, signup/auth, and Legal Center links.
5. Review whether existing users need notice before the change takes effect.
6. Run the legal-route and UI regression tests.

## Canonical routes

- `/legal` — Legal Center
- `/legal/privacy` — Privacy Policy
- `/legal/terms` — Terms of Service
- `/legal/acceptable-use` — Acceptable Use Policy
- `/legal/cookies` — Cookie & Local Storage Notice
- `/legal/billing` — Billing, Credits & Refund Policy
- `/legal/security` — Security & Responsible Disclosure
- `/legal/data-processing` — Data Processing & Retention Notice
- `/legal/third-parties` — Third-Party Services & Subprocessors
- `/legal/copyright` — Copyright & Content Takedown Policy

Short compatibility routes such as `/privacy`, `/terms`, `/acceptable-use`, `/cookies`, `/billing-policy`, and `/security` are also supported by the hosted app.

## Important maintenance note

These documents are operational legal templates aligned to the current Internet Hands implementation. They should be reviewed by qualified legal counsel before the Service is relied on for substantial commercial activity, regulated personal data, or broad international distribution.

Do not invent a company name, registered office, privacy officer, or legal email address in these files. Add those details only when the actual legal operator and contact channels are established.
