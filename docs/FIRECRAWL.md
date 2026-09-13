# Firecrawl Provider

Internet Hands v0.5 treats Firecrawl as a first-class web-context provider inside the same MCP Tool Mesh as Apify, Composio, OpenAPI sources, remote MCPs, gaming intelligence, and the native sandbox/browser plane.

Firecrawl is an accelerator, not a replacement for Internet Hands' own computer and data plane:

```text
Agent
  -> Internet Hands MCP
      -> semantic web capability
          -> Firecrawl v2 when configured
          -> Apify / native browser fallback where defined
      -> sandbox + live Chromium
      -> frontier + indexed captures + telemetry
```

## Configuration

Set the API key only on the Internet Hands server:

```env
FIRECRAWL_API_KEY=
```

The key is injected as a Bearer token by the provider. It is never included in tool descriptors, semantic capabilities, normal execution receipts, or agent arguments.

An operator may also point the provider at a Firecrawl-compatible/self-hosted deployment:

```env
FIRECRAWL_API_URL=https://api.firecrawl.dev
```

Clients and agents cannot choose the provider base URL at execution time.

## Raw Tool Mesh surface

The Firecrawl provider currently exposes:

- `firecrawl:search` — live web search with optional result-page scraping
- `firecrawl:scrape` — one-page JS-capable extraction into LLM-ready formats
- `firecrawl:map` — site URL discovery/ranking without a full crawl
- `firecrawl:crawl` — asynchronous site crawl
- `firecrawl:batch-scrape` — asynchronous multi-URL scrape
- `firecrawl:agent` — asynchronous Firecrawl research/extraction agent
- `firecrawl:extract` — structured extraction compatibility path
- `firecrawl:interact` — explicit browser interaction against a prior Firecrawl scrape session

The schemas intentionally allow additional Firecrawl v2 options so newly added extraction formats and bounded provider settings do not require a new Internet Hands release for every field.

`firecrawl:interact` is marked **side-effecting** because a browser prompt may click or submit page controls. It is never selected by a read-only semantic capability fallback. Internet Hands exposes it explicitly and restricts the mesh version to prompt-based interaction; arbitrary remote code execution through Firecrawl Interact is not exposed.

## Semantic collision with the existing web stack

The `web` capability pack composes providers rather than forcing the calling agent to choose a vendor:

- `web.fetch.page` — Firecrawl Scrape first, Apify Web Fetch fallback
- `web.search.live` — Firecrawl Search
- `web.research.rag` — Firecrawl Agent first, Apify RAG Web Browser fallback
- `web.map.site` — Firecrawl Map
- `web.crawl.site` — Firecrawl Crawl
- `web.scrape.batch` — Firecrawl Batch Scrape
- `web.extract.structured` — Firecrawl Agent first, Firecrawl Extract compatibility fallback

An agent can therefore use semantic intent instead of provider-specific names:

```text
mesh_route("crawl the documentation site")
mesh_capability_resolve("web.crawl.site")
mesh_capability_execute("web.crawl.site", {...})
```

## Async jobs and result paging

Firecrawl crawl, batch, agent, and extract executions return normalized Internet Hands job handles.

Example lifecycle:

```text
mesh_execute(
  ref="firecrawl:crawl",
  arguments={"url":"https://example.com","limit":100},
  wait_seconds=0
)
  -> job_id = "crawl:<firecrawl-id>"
  -> result_id = "crawl:<firecrawl-id>"

mesh_job_status(provider="firecrawl", job_id="crawl:<firecrawl-id>")

mesh_results(
  provider="firecrawl",
  result_id="crawl:<firecrawl-id>",
  offset=0,
  limit=100
)
```

Crawl and batch status pagination is mapped onto the common Tool Mesh `offset` / `limit` result API. Agents do not need to know Firecrawl's polling endpoint layout.

## Public-web and credential boundary

The Firecrawl provider follows Internet Hands' public-network defaults:

- explicit URL inputs are validated as public HTTP(S) targets
- target `Authorization`, `Cookie`, `Proxy-Authorization`, `X-API-Key`, and `X-RapidAPI-Key` headers are rejected through the mesh
- read-only `firecrawl:scrape` does not accept browser `actions`
- browser interaction is separated into the explicitly side-effecting `firecrawl:interact` tool
- provider credentials remain server-side
- Tool Mesh allow/deny rules and response-size bounds still apply

The purpose is to give an agent excellent public-web retrieval, not to turn Firecrawl into an authentication/session bypass layer.

## Parse/file ingestion

Firecrawl v2 also provides file parsing through multipart uploads. That is intentionally **not** represented as a JSON/base64 Tool Mesh call yet.

Internet Hands already has a sandbox/artifact subsystem. The cleaner future bridge is:

```text
sandbox artifact/file -> controlled multipart upload -> Firecrawl Parse -> normalized artifact/result
```

That avoids placing large file contents in model context or JSON tool arguments.

## Testing

CI uses mocked HTTP transports and fake provider responses. It verifies endpoint paths, server-side Bearer authentication, job/result normalization, side-effect classification, URL policy, and secret redaction without spending Firecrawl credits or requiring a live account.
