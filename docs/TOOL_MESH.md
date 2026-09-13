# Internet Hands Tool Mesh

Internet Hands v0.5 adds a provider-neutral external tool plane on top of the existing data, sandbox, and live-browser layers.

The goal is not to mirror a specific vendor. The mesh borrows the strongest ideas from Actor marketplaces and connected-app tool routers while keeping one Internet Hands execution contract.

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
        +-- Apify Actor catalog + runs + datasets
        +-- Composio connected-app tools
        +-- future ToolProvider adapters
```

Every external capability is represented as a normalized reference:

```text
provider:tool_id
```

Examples:

```text
apify:apify/web-scraper
composio:GITHUB_CREATE_ISSUE
```

## MCP tools

`mesh_providers` reports provider configuration and execution availability.

`mesh_search` searches enabled provider catalogs in parallel and interleaves results so one large catalog does not drown out the others.

`mesh_describe` retrieves normalized input/output schema and metadata before execution.

`mesh_execute` executes one tool. `dry_run=true` resolves the descriptor and call arguments without performing the provider action.

`mesh_batch_execute` fans out independent calls with a bounded concurrency and batch-size ceiling.

`mesh_job_status` handles long-running provider jobs. Apify Actor runs use this path.

`mesh_results` pages through provider result stores without forcing a large dataset into one MCP response.

## Apify provider

The Apify adapter treats public Store Actors as discoverable tools. Store search works without credentials. Executing an Actor requires `APIFY_TOKEN`.

Actor execution is asynchronous by default. A call can wait briefly for completion, but long runs return a `job_id` and, when available, a dataset `result_id`. The agent can continue later with `mesh_job_status` and `mesh_results`.

Supported run options are deliberately allowlisted: `build`, `memory`, `timeout`, `maxItems`, and `maxTotalChargeUsd`.

## Composio provider

The Composio adapter uses the current v3.1 tool catalog and direct tool execution API. Configure `COMPOSIO_API_KEY`, then `mesh_search` can discover tools across connected-app toolkits.

The optional `account` argument maps to a Composio connected-account id. This lets callers choose the exact connected account instead of relying on ambiguous account selection. Provider-specific `user_id`, `custom_auth_params`, `custom_connection_data`, and `version` values can be passed through `options` when required.

Composio direct tool results are returned inline, so generic job/result paging is not used for that provider.

## Policy and bounds

The mesh is intentionally bounded even when a provider can return much more data.

- `INTERNET_HANDS_TOOL_ALLOW`: optional comma-separated fnmatch allowlist. When set, only matching refs are visible and executable.
- `INTERNET_HANDS_TOOL_DENY`: optional deny patterns. Deny always wins.
- `INTERNET_HANDS_TOOL_MAX_BATCH`: maximum calls accepted by one batch request. Default: 20.
- `INTERNET_HANDS_TOOL_MAX_RESPONSE_BYTES`: maximum serialized provider payload returned inline. Default: 1,000,000 bytes.

Examples:

```text
INTERNET_HANDS_TOOL_ALLOW=apify:apify/*,composio:GITHUB_*
INTERNET_HANDS_TOOL_DENY=composio:*DELETE*,composio:*TRANSFER*
```

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

That contract is deliberately small. A provider can represent an Actor marketplace, an authenticated SaaS tool router, an MCP bridge, an OpenAPI catalog, or an internal enterprise tool registry without changing the agent-facing MCP surface.

## Design boundary

Internet Hands keeps its existing public-network and sandbox isolation rules. The Tool Mesh is an orchestration plane, not a way to weaken those boundaries. Provider credentials stay server-side, provider errors are normalized into execution receipts, and large outputs are paged or bounded before they enter model context.
