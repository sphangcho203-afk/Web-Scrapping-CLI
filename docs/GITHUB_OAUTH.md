# GitHub OAuth configuration

Create a GitHub OAuth App for the Internet Hands customer console.

For the current Vercel production origin:

- Homepage URL: `https://web-scrapping-cli.vercel.app/`
- Authorization callback URL: `https://web-scrapping-cli.vercel.app/api/auth/github/callback`

Server environment:

```text
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
```

The callback exchanges the authorization code server-side, fetches the GitHub profile/email, creates or updates the Internet Hands user, and issues the normal `ih_session` HttpOnly session cookie.

Do not use a personal access token as the customer-facing OAuth application secret.
