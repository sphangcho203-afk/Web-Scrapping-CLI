# Third-Party Services & Subprocessors

**Policy version:** 2026-09-20  
**Effective date:** 20 September 2026  
**Last updated:** 20 September 2026

External providers Internet Hands may rely on for hosting, payments, email, authentication, web data, connected apps, and execution.

## 1. How external providers are used

Internet Hands is a routing and execution layer, so some requested operations necessarily involve external providers. Not every deployment or request uses every provider listed below. The exact provider path depends on configuration, capability, region, and the instruction you submit.

## 2. Current provider categories

| Provider / category | Typical purpose | Data involved |
| --- | --- | --- |
| Vercel | Hosting, edge delivery, deployment, and serverless execution | HTTP requests, application responses, operational logs. |
| PostgreSQL / Neon where configured | Account, control-plane, usage, security, monitor, and billing records | Account identifiers, configuration, usage, and audit data. |
| Razorpay | Payment checkout and transaction verification | Payment details handled by Razorpay; Internet Hands receives order/payment references, amount, and status. |
| Resend or configured SMTP provider | Transactional email | Email address, message content, and delivery metadata. |
| GitHub | OAuth sign-in and repository-related integrations where requested | GitHub identity and authorization data. |
| Composio where configured | Connected-app discovery and execution | User-directed tool inputs, connected-account identifiers, and execution results. |
| Firecrawl / Brave Search / other configured web-data providers | Search, scrape, map, crawl, and web discovery | Queries, target URLs, retrieved public content, and provider metadata. |
| Remote MCP servers, APIs, browser or sandbox providers | User-directed execution | Only the instructions, credentials, content, and results needed for the selected operation. |

## 3. User-directed transfers

When you explicitly choose or invoke an integration, API, remote MCP server, browser, or other provider, the resulting transfer is part of the operation you requested. Review the destination and scope before sending confidential or regulated information.

## 4. Provider changes

Providers may be added, replaced, or removed as the product evolves. We update this page when a change materially affects the categories of personal information processed or the role of a provider.

## 5. Third-party terms

Third-party services are independent from Internet Hands and may impose their own terms, rate limits, acceptable-use rules, data-retention practices, or geographic restrictions. Your use of those services remains subject to their applicable terms.

---

Hosted version: `/legal` and the matching `/legal/<policy>` route.