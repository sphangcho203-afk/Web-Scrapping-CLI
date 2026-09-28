# Connect to OpenCrawl MCP

OpenCrawl's inbound endpoint is `https://YOUR-OPENCRAWL-HOST/mcp` (Streamable HTTP). The public capability registry describes registered outcomes; a connected client's `tools/list` is filtered by its key or OAuth grant and plan. `account_available_actions` and the Connections page show eligible concrete routes for that account. A provider's health and required inputs are checked again during execution.

## API key

1. Create a dedicated key under **Dashboard → API keys**. Grant `mcp:read` and `mcp:execute`; optionally add `account:read` and `monitors:read`.
2. In the MCP client, configure the endpoint and send `Authorization: Bearer <OpenCrawl key>` on every request. `X-API-Key: <OpenCrawl key>` is accepted as an alternative.
3. Refresh the client connection. It should initialize and list the tools allowed by that credential. Revoke the key to immediately block future calls.

A minimal protocol probe, with the key read from a shell environment variable:

```sh
curl -i 'https://YOUR-OPENCRAWL-HOST/mcp/' \
  -H "Authorization: Bearer $OPENCRAWL_API_KEY" \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"connection-check","version":"1"}}}'
```

The response should be HTTP 200 with `result.serverInfo`. A full MCP client then sends `tools/list`; curl by itself does not run a complete session. A 401 includes a `WWW-Authenticate` pointer to OAuth protected resource metadata.

## OAuth (PKCE)

Point an OAuth-capable MCP client at the same URL. The client discovers `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server`, dynamically registers at `/oauth/register`, and performs authorization code with PKCE S256. The browser signs the user in to OpenCrawl, preserves the original authorization request through email verification or 2FA when needed, shows the requested scopes, and asks for explicit approval. The client receives a short-lived access token and rotating refresh token; it never receives the user's password, web session cookie, or API keys. The authorization and token requests may include `resource=https://YOUR-OPENCRAWL-HOST/mcp`; tokens are bound to that endpoint. Use the same host for authorization, token exchange, and MCP calls.

`offline_access` permits refresh. OAuth grants are account-scoped and independent from machine API keys; API-key authentication remains a separate connection mode. Keep `INTERNET_HANDS_OAUTH_SIGNING_SECRET` configured consistently across deployments so dynamically registered client IDs remain valid.

## Public endpoint requirement

External MCP registries must be able to reach the server **before** OpenCrawl authentication runs. Use a stable public HTTPS origin such as the production/custom domain. Do not register a Vercel preview hostname protected by Vercel Authentication: the platform can intercept `/.well-known/oauth-*` or `/mcp` before OpenCrawl sees the request, which looks like an OpenCrawl authentication failure even when the gateway code is healthy.

A useful diagnostic split is:

1. Anonymous `GET /.well-known/oauth-protected-resource` must reach OpenCrawl and return JSON.
2. Anonymous MCP initialize should reach OpenCrawl and return its own `401` plus `WWW-Authenticate` metadata.
3. Only then test the API key or OAuth grant.
4. After authentication succeeds, run `tools/list` and then `account_available_actions` for the account-specific executable surface.

## Composio Custom MCP

Composio's experimental Custom MCP integration is separate from OpenCrawl's outbound connected apps. Register OpenCrawl's public HTTPS URL as a `CUSTOM_*` toolkit. Select one authentication scheme at registration:

- API key: `API_KEY` with a header template such as `Authorization: Bearer {{generic_api_key}}`. Create the Composio auth config and connect an account using a dedicated OpenCrawl key.
- OAuth: `DCR_OAUTH` with the OpenCrawl authorization server discovery URL. Create its auth config, sign in to the OpenCrawl account in the browser, review the requested scopes, and approve the grant. No OpenCrawl API key is pasted into the consent screen.

Composio requires an auth config for an authenticated custom toolkit. Set `is_enabled_for_tool_router: true` when automatic account matching is wanted, or pin the connected account ID in the session. The first sync begins after an account becomes active; retry `POST /api/v3.1/custom/toolkits/sync` with its `connected_account_id` if needed. Composio cannot change a toolkit's URL or auth scheme in place; replacing those fields requires deleting and registering again, which also removes its connections. See the [Composio Custom MCP documentation](https://docs.composio.dev/docs/extending-sessions/custom-mcp) for current request schemas.

If a Composio account appears active yet says **No tools available** and **Authentication failed**, verify the exact URL, scheme and header/token that account sends. Probe OpenCrawl's initialize with that same credential, reconnect with a valid key or OAuth grant, then retry sync. Composio's v3 tools listing can show an empty list for custom toolkits unless `toolkit_versions=latest` is set; use v3.1 or explicitly select the latest version.

## Availability semantics

The public `/api/public/capabilities` remains an unfiltered registry. Authenticated `/api/available-actions?query=...` and MCP `account_available_actions` return registered capabilities with a concrete route, a currently executable provider and a plan-eligible estimate. Dynamic search candidates, unverified remote MCP tool refs and unverified connected-app actions are not presented as ready. These lists are a snapshot of eligibility, not a promise that an upstream request will succeed. MCP `tools/list` returns the smaller, scoped OpenCrawl entry points that the credential can invoke; use `account_available_actions`, then resolve/describe before execution.
