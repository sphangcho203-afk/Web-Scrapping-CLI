# GitHub OAuth configuration

Create a GitHub OAuth App for the OpenCrawl customer console.

For the canonical OpenCrawl production origin:

- Homepage URL: `https://opencrawl.top/`
- Authorization callback URL: `https://opencrawl.top/api/auth/github/callback`

Server environment:

```text
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
```

The callback exchanges the authorization code server-side, fetches the GitHub profile/email, creates or updates the OpenCrawl user, and issues the normal `ih_session` HttpOnly session cookie.

Do not use a personal access token as the customer-facing OAuth application secret.
