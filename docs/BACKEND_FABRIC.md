# Internet Hands backend fabric

Internet Hands keeps policy, provenance, indexing, and orchestration in one control plane while allowing specialized collection engines to sit behind it.

## Design rule

A cloned backend is **not** automatically trusted or executable. Internet Hands records the exact upstream commit, verifies the curated origin, reports runtime readiness separately, and routes only to a backend that is actually installed/configured.

```text
query / seed URL / agent task
          |
          v
 search + endpoint discovery
          |
          v
    intent router
   /   |    |    \
HTTP browser crawl extract
 |     |     |      |
native Playwright Crawlee Trafilatura
       MCP      Scrapy Crawl4AI
   \     |      |    /
    normalized capture
          |
   policy + provenance
          |
 object store + SQLite/FTS5
          |
 search / watch / API / agent
```

## Curated engines

| Backend | Role | License posture | Integration state |
| --- | --- | --- | --- |
| Internet Hands native HTTP | exact-byte fetch, bounded hunt, indexing | project MIT | active |
| Native Playwright | guarded JS rendering | Playwright dependency | active optional extra |
| Microsoft Playwright MCP | persistent agent/browser interaction | Apache-2.0 | MCP sidecar config ready |
| Crawlee Python | queues, retries, sessions, scalable HTTP/browser crawl | Apache-2.0 | curated/staged worker backend |
| Scrapy | high-throughput asynchronous HTTP crawling | BSD-3-Clause | curated/staged worker backend |
| Crawl4AI | LLM-oriented browser extraction | Apache-2.0 plus upstream attribution requirement | curated/staged worker backend |
| Trafilatura | article/main-text + metadata extraction | Apache-2.0 | active optional extraction backend |
| Firecrawl | optional self-hosted web-data service | AGPL-3.0 core | external-service only by default |

Firecrawl is deliberately not cloned by `ih-backends sync all`. Vendoring its AGPL core into the MIT source tree would require an intentional licensing decision.

## Commands

```bash
# Inventory curated engines and licenses
ih-backends list

# Clone/update the permissively licensed default source backends.
# Every clone records the exact upstream commit under .internet-hands/backends/.
ih-backends sync all

# Distinguish cloned source from an actually runnable backend.
ih-backends status

# Ask the router what should handle a job.
ih-backends plan static
ih-backends plan dynamic
ih-backends plan interactive
ih-backends plan throughput
ih-backends plan article
ih-backends plan llm-extraction

# Print portable Microsoft Playwright MCP configuration.
ih-backends playwright-mcp-config
```

## Microsoft Playwright MCP

The official server is configured with:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest"]
    }
  }
}
```

The current default MCP capability set includes browser navigation, snapshots, element finding, clicking, typing/forms, keyboard input, dialogs, tabs, screenshots, console/network inspection, evaluation, uploads, drag/drop, resize and waits. The upstream capability test currently enumerates these default tool names:

- `browser_click`
- `browser_console_messages`
- `browser_drag`
- `browser_drop`
- `browser_evaluate`
- `browser_file_upload`
- `browser_fill_form`
- `browser_find`
- `browser_handle_dialog`
- `browser_hover`
- `browser_select_option`
- `browser_type`
- `browser_close`
- `browser_navigate_back`
- `browser_navigate`
- `browser_network_request`
- `browser_network_requests`
- `browser_press_key`
- `browser_resize`
- `browser_run_code_unsafe`
- `browser_snapshot`
- `browser_tabs`
- `browser_take_screenshot`
- `browser_wait_for`

Optional upstream capability groups add PDF save and coordinate-based vision/mouse tools.

Internet Hands does not expose `browser_run_code_unsafe` through its own remote HTTP API. MCP clients remain responsible for their own tool permissions and approvals.

## Hunt pipeline

`ih-hunt` is the built-in bounded frontier. It can start from explicit URLs, Brave Search results, or both.

```bash
# Same-origin crawl/index.
ih-hunt run --seed https://example.com --max-pages 200 --max-depth 4

# Search-seeded web hunt with explicit domain/page budgets.
ih-hunt run \
  --query "open source retrieval systems" \
  --scope web \
  --search-count 10 \
  --max-domains 20 \
  --max-pages 300

# Add guarded Playwright rendering for JS-heavy pages.
pip install -e '.[browser]'
playwright install chromium
ih-hunt run --seed https://example.com --browser-fallback
```

The frontier performs URL canonicalization, tracker removal, URL/content deduplication, depth/page/domain caps, per-host pacing and `robots.txt` checks by default. It also expands published RSS/Atom/JSON feeds, sitemap `<loc>` entries and machine-readable interface links.

## Extraction backend

Install the current Trafilatura 2.x integration with:

```bash
pip install -e '.[extraction]'
```

Internet Hands first preserves the original response. For HTML, Trafilatura may then improve main text/title/description. Native link extraction remains authoritative for the frontier, and any Trafilatura failure falls back to the native parser without aborting collection.

## Backend routing

The router distinguishes:

- `native` — built into Internet Hands;
- `runtime-ready` — dependency/command is installed and executable;
- `staged-source` — curated source is cloned but not installed;
- `external-service` — intentionally kept outside the process;
- `unavailable` — neither installed nor staged.

This prevents a common failure mode where an orchestration layer reports a backend as usable merely because a repository exists on disk.

## Collection boundary

The fabric is for public data and sources the operator is authorized to access. The backend layer does not add CAPTCHA solving, authentication bypass, credential theft, stealth/evasion, quota-evasion key rotation, or private-network crawling. Browser requests remain subject to public-network filtering, and production deployments should add network-level egress enforcement as a second boundary.
