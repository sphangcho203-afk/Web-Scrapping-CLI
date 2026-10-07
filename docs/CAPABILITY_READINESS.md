# Capability readiness

A registered capability is an operation contract, not a guarantee that its external
credentials, account connection, or execution environment are configured.

`mesh_capability_resolve` reports `available`, `reason_code`, and an actionable
`reason` for each route. Discovery has an eight-second total deadline and never
executes an operation. Provider errors are classified without returning their URLs,
response bodies, account IDs, or credentials in the reason.

Verified signed-in users can inspect any registered pack with
`GET /api/capabilities/{capability_id}/availability`. This endpoint uses the user's
identity, exposes only readiness and setup messages, reserves zero credits, and
returns `Cache-Control: no-store`. It does not make connected write operations
available in the read-only web workbench.

Authenticated MCP execution checks semantic route readiness before reserving
credits for `mesh_capability_execute` and `gaming_intel`. An unavailable route
returns HTTP 409 `capability_unavailable` with no wallet reservation or usage
settlement. A gaming batch is admitted only after every requested operation passes
preflight; inspection concurrency is five, with a ten-second batch deadline.
Execution still rechecks routing and ownership. Readiness is a snapshot: a provider
can fail after preflight, and the usual execution settlement rules then apply.
Dry runs can inspect a discoverable schema without configured execution credentials.
Side-effecting calls still require explicit permission and never retry another
backend after execution starts.

The web workbench and gaming operation chooser display setup reasons before a user
reviews cost. Discovery and gaming execution carry the caller's identity so owned
connections are checked under that caller rather than the project context. Unavailable gaming tools cannot be submitted to the runner.

## Production audit blockers (2026-10-07)

The deep audit inspected the first 100 sorted capabilities and found 12 unavailable
routes. Keep the strict audit enabled until they are genuinely ready. This release
improves diagnosis and billing admission; it does not provision missing credentials
or share private connected accounts.

| Capabilities | Required setup |
| --- | --- |
| `ads.meta.library` | Configure the existing Apify route with `APIFY_TOKEN` and confirm access to its registered actor. |
| `automation.workflow`, `automation.workflow.status` | Register and sync the custom N8N toolkit in the Composio project used by OpenCrawl. Confirm the exact execution/status slugs and an active connection belonging to the OpenCrawl caller. The configured REST bridge returned 404 for the current slugs. |
| `brawlstars.brawlers.reference`, `brawlstars.matches.recent`, `brawlstars.player.profile` | Configure `BRAWL_STARS_AUTHORIZATION` with the complete official API Authorization header value. |
| `clashofclans.player.profile`, `clashofclans.rank.history` | Configure `CLASH_OF_CLANS_AUTHORIZATION` with the complete official API Authorization header value. |
| `clashroyale.matches.recent`, `clashroyale.player.profile`, `clashroyale.progression.chests` | Configure `CLASH_ROYALE_AUTHORIZATION` with the complete official API Authorization header value. |
| `code.execute` | Connect the registered Higgsfield execution tool for the caller, or configure the existing isolated Vercel Sandbox route with its supported token and project ID. Do not fall back to executing on the application host. |

Presence of a key does not prove its validity or upstream access. After setup, use
owned availability inspection, then a bounded authorized operation, and inspect
credit settlement. Official gaming API tokens can also require compatible source-IP
configuration; follow each provider's developer portal rather than bypassing it.

Composio's custom MCP toolkits are project scoped. A tool visible in a different
agent's Composio session is not evidence that OpenCrawl's project can resolve or
execute it. The bridge uses v3.1, which selects the latest custom toolkit version.
Registration and tool synchronization follow the
[official Custom MCP documentation](https://docs.composio.dev/docs/extending-sessions/custom-mcp).

The existing daily product tracker remains enabled with its user-approved three-credit
maximum per check. Its first scheduled check was not yet due during this release's
inspection. Do not alter the schedule or manufacture a product change to claim
live scheduled settlement or change-email delivery.
