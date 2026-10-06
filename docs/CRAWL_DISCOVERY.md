# Sitemap discovery and crawl bounds

Enable **Discover pages from sitemaps** in Playground's Advanced options for either an immediate URL crawl or a background crawl. Headless clients can send `"discover_sitemaps": true` to `POST /api/playground/run` or `POST /api/crawl-runs`. The native `nativeweb:crawl` tool accepts the same boolean.

The option defaults to false, preserving link-only crawling and existing checkpoints. Content monitors remain one-page checks and do not discover sitemaps.

## Discovery contract

The crawler captures the seed first, then reads sitemap hints from that page origin's robots.txt. If there are no hints, it checks `/sitemap.xml` on that origin. XML `urlset` documents add page URLs; `sitemapindex` documents add bounded child sitemap requests. Entries are absolute URLs. Duplicate URLs and index cycles are suppressed. Sitemap pages enter the existing frontier at depth 1, share its page and content limits, and can yield further HTML links within the selected depth. A depth-zero crawl performs no sitemap requests.

Each crawl checks at most 8 sitemap documents, captures at most 512,000 bytes per document, and reads at most 1000 locations per document. Gzip sitemap files, text sitemaps, cross-site sitemap hosting and JavaScript rendering are not supported in this slice. XML DTD/entity declarations, malformed documents and unexpected roots are rejected. The supported XML shape follows the [Sitemaps protocol](https://www.sitemaps.org/protocol.html).

Every sitemap request and redirect uses the existing public DNS/peer checks, robots policy, transport/port limits and configured site/subdomain scope. Sitemap hints cannot widen that scope. Include patterns apply to discovered pages, while exclude patterns also protect sitemap requests. Apex/`www` aliases share the configured subdomain scope. Concurrent pages on a new origin share one robots request.

Sitemap errors preserve the pages already captured. `sitemap_documents` counts attempted document checks; `sitemap_urls` counts additional unique URLs accepted into the frontier, including URLs later blocked by robots. `sitemap_errors` contains up to eight bounded diagnostic messages; `sitemap_truncated` reports a discovery limit or timeout. These fields are part of saved output. Background progress exposes the counts, a truncation flag and an error count, without retaining a second copy of sitemap diagnostics after completion.

## Time, memory and recovery

The overall crawl time limit now cancels in-flight asynchronous page, robots and sitemap I/O and returns the captures completed so far. A timed-out page carries an explicit error. The worker allows a small finalization margin for the crawler to persist its final checkpoint, within its existing worker failsafe. Synchronous DNS resolution and database finalization are separate existing boundaries; this is not a guarantee of exact end-to-end request latency.

All crawling modes now limit the frontier to 1000 URLs, 500,000 aggregate URL bytes and 4096 bytes per URL. Exceeding these limits sets `frontier_truncated`. A fully exhausted one-page site is complete even when its page count equals the configured maximum. Playground reports output as partial when a crawl/discovery limit is reached.

Discovery finishes or times out before the first batch checkpoint. Recovery carries its accepted frontier, counters and diagnostics, does not reread sitemap documents, and refreshes robots before requesting pending pages. Existing link-only checkpoint hashes remain compatible; a sitemap-enabled checkpoint cannot be resumed with different discovery controls. Uncommitted work may repeat after a process crash, under the existing fenced worker/reservation model.

Sitemap/robots/page attempts use the existing native request meter and reservation. Discovery does not create a separate completion charge or customer reservation.

## Verification

Regression checks exercise the real HTTP fetcher with a deterministic transport and public DNS boundary: unlinked-page discovery, namespaces and indexes, deduplication, cycles, path filters, robots denial, guarded redirects, private DNS, byte/location/document limits, original time budgets, checkpoints and request metering. CI runs an owned worker against PostgreSQL and verifies saved rows, progress and measured usage. Chromium checks both submission paths and truthful partial-result labels.

Preview readiness and fixture checks do not verify the authenticated deployed account flow. Production promotion retains the existing deployed verification gate.
