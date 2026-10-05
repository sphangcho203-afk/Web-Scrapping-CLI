# OpenCrawl production rollout checklist

Canonical production origin: `https://opencrawl.top`
Permanent MCP endpoint: `https://opencrawl.top/mcp`
GitHub OAuth callback: `https://opencrawl.top/api/auth/github/callback`
Razorpay webhook: `https://opencrawl.top/api/webhooks/razorpay`


- [ ] v0.6 CI green on Python 3.11, 3.12, and 3.13
- [ ] Vercel preview deploys from `feat/v0.6-saas-control-plane`
- [ ] `/` renders the website
- [ ] `/api/status` reports control DB, GitHub OAuth, and Razorpay configuration
- [ ] `https://opencrawl.top/.well-known/oauth-protected-resource` returns MCP metadata advertising `https://opencrawl.top/mcp`
- [ ] `/.well-known/oauth-authorization-server` returns authorization/token endpoints
- [ ] unauthenticated `https://opencrawl.top/mcp` returns 401 with `WWW-Authenticate`
- [ ] email signup/login works
- [ ] GitHub OAuth App callback is set to `https://opencrawl.top/api/auth/github/callback` and sign-in completes
- [ ] API key creation shows the secret exactly once
- [ ] MCP authorization-code + PKCE flow exchanges an API key for short-lived bearer credentials
- [ ] customer MCP calls are metered and visible in `/dashboard/usage`
- [ ] Free plan wallet starts with 2,500 monthly credits
- [ ] Razorpay order creation uses server-side prices only
- [ ] Razorpay payment verification grants value only after `captured`
- [ ] Razorpay webhook signature rejection works with a deliberately invalid signature
- [ ] No live payment is created during rollout verification unless explicitly approved
- [ ] password reset returns a generic response for both existing and unknown email addresses
- [ ] monitors CRUD respects plan limits
- [ ] production branch is not switched until all applicable checks above pass
