# Internet Hands Tool Mesh

Internet Hands v0.5 adds a provider-neutral capability plane on top of the existing data, sandbox, and live-browser layers.

The goal is not to mirror one vendor. The mesh combines Actor marketplaces, connected-app routers, API catalogs, OpenAPI discovery, remote MCP servers, and curated capability packs behind one Internet Hands execution contract.

## Mental model

```text
agent
  |
  v
Internet Hands MCP
  |
  +-- sandbox/browser tools
  +-- crawl/frontier/content tools
  +-- Tool Mesh
        |
        +-- semantic capability packs
        +-- Apify Actor catalog + runs + datasets
        +-- Composio connected-app tools
        +-- RapidAPI manifest tools
        +-- public HTTP manifest tools
        +-- read-only OpenAPI catalogs
        +-- configured public remote MCP servers
```

Every raw external capability is represented as a normalized reference:

```text
provider:tool_id
```

Examples:

```text
apify:apify/web-scraper
composio:GITHUB_CREATE_ISSUE
rapidapi:mlbb-player-lookup
publicapi:mlbb-nickname-lookup
openapi:rone-mlbb::operationId
mcp:source-name::tool-name
```

Agents do not need to know those refs for common tasks. Semantic packs expose names such as `mlbb.player.lookup` and resolve the best available provider automatically.

## MCP tools

`mesh_providers` reports provider configuration and execution availability.

`mesh_search` searches enabled provider catalogs in parallel and interleaves results so one large catalog does not drown out the others.

`mesh_describe` retrieves normalized input/output schema and metadata before execution.

`mesh_execute` executes one tool. `dry_run=true` resolves the descriptor and call arguments without performing the provider action.

`mesh_batch_execute` fans out independent calls with a bounded concurrency and batch-size ceiling.

`mesh_job_status` handles long-running provider jobs. Apify Actor runs use this path.

`mesh_results` pages through provider result stores without forcing a large dataset into one MCP response.

`mesh_capabilities` searches semantic capability packs.

`mesh_capability_resolve` shows the ranked concrete providers behind a semantic capability.

`mesh_capability_execute` runs a semantic read-only capability and may fall back to another provider when the preferred source is unavailable.

## Apify provider

The Apify adapter treats public Store Actors as discoverable tools. Store search works without credentials. Executing an Actor requires `APIFY_TOKEN`.

Actor execution is asynchronous by default. A call can wait briefly for completion, but long runs return a `job_id` and, when available, a dataset `result_id`. The agent can continue later with `mesh_job_status` and `mesh_results`.

Supported run options are deliberately allowlisted: `build`, `memory`, `timeout`, `maxItems`, and `maxTotalChargeUsd`.

## Composio provider

The Composio adapter uses the v3.1 tool catalog and direct tool execution API. Configure `COMPOSIO_API_KEY`, then `mesh_search` can discover tools across connected-app toolkits.

The optional `account` argument maps to a Composio connected-account id. This lets callers choose the exact connected account instead of relying on ambiguous account selection. Provider-specific `user_id`, `custom_auth_params`, `custom_connection_data`, and `version` values can be passed through `options` when required.

Composio direct tool results are returned inline, so generic job/result paging is not used for that provider.

## RapidAPI + manifest HTTP providers

`rapidapi` and `publicapi` are small schema-first HTTP catalogs. They only execute curated read-only `GET`/`HEAD` operations.

`RAPIDAPI_KEY` stays server-side. Internet Hands injects it into the RapidAPI request and never places the key in tool descriptors or execution receipts.

Additional tools can be registered without changing Python by setting `INTERNET_HANDS_RAPIDAPI_TOOLS` or `INTERNET_HANDS_PUBLIC_API_TOOLS` to a JSON array. A manifest entry uses this shape:

```json
{
  "tool_id": "example-search",
  "name": "Example search",
  "description": "Search public example data",
  "method": "GET",
  "base_url": "https://example.p.rapidapi.com",
  "path": "/search",
  "parameters": {
    "q": {"in": "query", "required": true, "schema": {"type": "string"}}
  },
  "tags": ["search"],
  "requires_auth": true,
  "host_header": "example.p.rapidapi.com",
  "auth_env": "RAPIDAPI_KEY",
  "auth_header": "X-RapidAPI-Key"
}
```

Non-read methods are rejected by the manifest loader.

## OpenAPI provider

The `openapi` provider turns configured public OpenAPI documents into searchable mesh tools dynamically. It imports only `GET` and `HEAD` operations. Private/loopback/link-local targets are rejected by Internet Hands network policy.

Rone Arena's public MLBB OpenAPI document is included as the first built-in catalog. Additional public documents can be configured with `INTERNET_HANDS_OPENAPI_SOURCES`:

```json
[
  {"name": "example", "url": "https://api.example.com/openapi.json"}
]
```

The provider caches schemas briefly, converts operation parameters into JSON Schema, and executes against the server declared by the OpenAPI document.

## Remote MCP provider

`INTERNET_HANDS_REMOTE_MCP_SOURCES` joins configured public Streamable-HTTP MCP servers to the same Tool Mesh:

```json
[
  {"name": "example", "url": "https://mcp.example.com/mcp"}
]
```

Internet Hands validates the endpoint as public before connecting. In v0.5 this bridge intentionally targets public MCP endpoints only. Connected/authenticated app actions should go through the Composio plane instead.

Remote tools are considered potentially side-effecting unless the upstream MCP descriptor explicitly marks them read-only. Remote descriptions/results are also tagged as untrusted external data.

## Capability packs

Capability packs prevent the agent from needing to memorize which marketplace currently has the best implementation.

The first built-in pack is `mlbb` and currently defines semantic operations for:

- player lookup
- nickname lookup
- hero list
- hero detail
- hero analytics/statistics
- academy items
- academy spells
- academy emblems
- rank/reference data

`mlbb.player.lookup` prefers the configured RapidAPI player-information source. If that read-only source is unavailable, the pack can fall back to a nickname-only public community endpoint when the required player and zone identifiers are available.

Hero/academy/reference capabilities are resolved dynamically against the Rone Arena OpenAPI catalog, so Internet Hands does not freeze endpoint paths into the agent prompt.

Capability fallback is only automatic for read-only operations. A side-effecting tool is never silently substituted for another tool.

## Policy and bounds

The mesh is intentionally bounded even when a provider can return much more data.

- `INTERNET_HANDS_TOOL_ALLOW`: optional comma-separated fnmatch allowlist. When set, only matching refs are visible and executable.
- `INTERNET_HANDS_TOOL_DENY`: optional deny patterns. Deny always wins.
- `INTERNET_HANDS_TOOL_MAX_BATCH`: maximum calls accepted by one batch request. Default: 20.
- `INTERNET_HANDS_TOOL_MAX_RESPONSE_BYTES`: maximum serialized provider payload returned inline. Default: 1,000,000 bytes.

Examples:

```text
INTERNET_HANDS_TOOL_ALLOW=apify:apify/*,composio:GITHUB_*,openapi:rone-mlbb::*
INTERNET_HANDS_TOOL_DENY=composio:*DELETE*,composio:*TRANSFER*
```

A default marketplace safety filter also removes restricted categories from discovery and execution before provider-specific allow/deny rules are considered.

The mesh never returns provider API keys in descriptors, status payloads, or execution receipts.

## Provider contract

New ecosystems implement `ToolProvider` from `tool_mesh.py`:

```python
class ToolProvider(Protocol):
    name: str

    async def status(...): ...
    async def search(...): ...
    async def describe(...): ...
    async def execute(...): ...
    async def job_status(...): ...
    async def result_page(...): ...
```

That contract is deliberately small. A provider can represent an Actor marketplace, an authenticated SaaS tool router, a remote MCP bridge, an OpenAPI catalog, an API marketplace, or an internal enterprise tool registry without changing the agent-facing MCP surface.

## Design boundary

Internet Hands keeps its existing public-network and sandbox isolation rules. The Tool Mesh is an orchestration plane, not a way to weaken those boundaries. Provider credentials stay server-side, provider errors are normalized into execution receipts, external content is treated as untrusted, and large outputs are paged or bounded before they enter model context.

## Connected semantic capability plane

Connected SaaS and automation tools are also exposed through stable semantic
capabilities so an agent does not need to memorize vendor-specific tool slugs.

Current built-ins:

- browser.navigate — start a natural-language browser automation task
- browser.task.status — inspect browser progress/results
- automation.workflow — execute a connected workflow
- automation.workflow.status — inspect one workflow execution
- messaging.send — send through Telegram or Discord using platform
- code.execute — run a command in an isolated connected cloud sandbox

These capabilities normalize their arguments before calling the provider. For
example, messaging.send accepts platform, target, and message; the registry maps
those to the selected backend's concrete schema and drops provider-irrelevant
fields.

Side-effecting capabilities are fail-closed. A real execution requires
allow_side_effects=true. Without that flag, callers can still use dry_run=true to
resolve the backend and inspect the normalized call. This gate is in addition to
Tool Mesh allow/deny policy and the Composio connected-account allowlist.

The optional account argument on mesh_capability_execute is passed through to
the provider layer. For Composio, the connected-account bridge still enforces
its allowlist and rejects ambiguous account routing rather than guessing.

Automatic fallback remains conservative: read-only capabilities may try a later
provider when the preferred source is unavailable; write capabilities never
silently retry a different side-effecting backend after an execution attempt.
