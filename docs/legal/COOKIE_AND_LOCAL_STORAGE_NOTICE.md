# Cookie & Local Storage Notice

**Policy version:** 2026-09-20  
**Effective date:** 20 September 2026  
**Last updated:** 20 September 2026

A plain-language inventory of browser storage Internet Hands currently needs and what it does not use for advertising.

## 1. Current browser storage

| Purpose | Typical duration | Why it exists |
| --- | --- | --- |
| Signed-in session | Up to 30 days unless revoked | Keeps an authenticated browser session without exposing the raw server-side session record. |
| Two-factor challenge | About 10 minutes | Carries a short-lived challenge between primary sign-in and authenticator/recovery-code verification. |
| OAuth / authorization state | Short-lived | Protects and completes authorization, consent, and redirect flows. |
| Hosting preview protection | Provider controlled on protected previews | Preview deployments may set hosting-platform authentication or feedback cookies. These are separate from the public production Service. |

## 2. Advertising and tracking

The current first-party Internet Hands application does not use advertising cookies for behavioral profiling and does not use browser localStorage to build advertising profiles. If optional analytics or advertising storage is introduced later, this notice will be updated and controls will be provided where required.

## 3. Your controls

Most browsers let you delete or block cookies. Blocking strictly necessary authentication or security cookies may prevent sign-in, two-factor verification, OAuth authorization, or other account features from working.

Signing out or revoking sessions invalidates server-side session access even if a browser retains an expired cookie value.

---

Hosted version: `/legal` and the matching `/legal/<policy>` route.