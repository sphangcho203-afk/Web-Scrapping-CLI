# Internet Hands v0.3 — Endpoint Fabric

Internet Hands is evolving from a web fetcher into a capability-driven public internet
intelligence fabric. The goal is broad, composable access to public and explicitly
authorized data while keeping source provenance, provider rules, and network policy visible.

## Design rule

Do not build one giant scraper full of provider-specific conditionals.

Build a fabric:

```text
input target
   │
   ▼
resolver / classifier
   │
   ├── URL
   ├── username / handle
   ├── YouTube video or channel
   ├── API resource
   ├── research identifier
   └── OpenAPI specification
   │
   ▼
capability router
   │
   ├── profile
   ├── posts
   ├── video
   ├── channel
   ├── search
   ├── comments
   ├── live
   ├── repositories
   ├── package
   ├── research
   ├── analytics
   └── revenue
   │
   ▼
provider adapter
   │
   ├── official/public API
   ├── public HTTP capture
   ├── browser rendering
   ├── OpenAPI-discovered read operation
   └── explicitly authorized user API
   │
   ▼
normalized record + provenance
   │
   ├── raw response
   ├── extracted fields
   ├── source endpoint
   ├── timestamp
   ├── hash
   ├── auth/public-data classification
   └── derived signals
   │
   ▼
index / watches / agents / analysis
```

"Limitless endpoints" should mean **extensible endpoint coverage**, not pretending real
providers have no quotas or access rules. The router should use the best available lawful
source, degrade gracefully, and surface rate-limit/auth state instead of silently bypassing it.

## Built-in endpoint catalog

`src/internet_hands/endpoints.py` is the first capability catalog. It currently describes
provider operations across:

- YouTube Data API and owner-authorized YouTube Analytics
- GitHub REST API
- Bluesky public AppView
- Hacker News Firebase API
- Mastodon public API
- Twitch Helix
- TikTok Display API with user authorization
- Reddit OAuth API
- GitLab public REST API
- Wikipedia / MediaWiki
- Wikidata SPARQL
- OpenAlex
- Crossref
- npm registry
- PyPI
- crates.io

The catalog records provider, operation name, capability, method, endpoint, auth mode,
required environment variables, public/private classification, and readiness.

```bash
ih endpoints

ih endpoints --provider youtube

ih endpoints --capability profile --ready-only
```

## OpenAPI discovery

`ih-openapi` turns a public OpenAPI JSON or YAML document into an inventory of read-only
operations.

```bash
ih-openapi discover https://example.com/openapi.json
```

The discovery layer imports only `GET` and `HEAD` operations. It extracts:

- server URLs
- operation IDs
- paths and methods
- tags
- parameter names and locations
- summaries/descriptions
- an inferred capability
- a SHA-256 provenance hash of the source specification

OpenAPI discovery is intentionally separate from blind execution. Before an operation becomes
an executable adapter, the system should know its authentication requirements, provider rules,
rate limits, and output schema.

## Social and identity intelligence

The v0.3 collector layer provides provider-specific functions for:

- YouTube video metadata/statistics
- YouTube channel metadata/statistics by ID or `@handle`
- YouTube owner analytics and monetary metrics with explicit OAuth authorization
- GitHub public profiles and public repositories
- Bluesky public profiles and author feeds
- Hacker News items/users
- Mastodon public account lookup on an explicit instance
- Twitch user lookup with configured application credentials
- TikTok profile data for the user who authorized the access token
- exact public username checks across selected public providers

Exact-handle checking is deliberately not phone/email reverse lookup and does not attempt to
recover private identities. A future identity graph should keep every cross-platform link as an
explicit confidence-scored claim rather than treating matching usernames as proof that accounts
belong to the same person.

## YouTube video intelligence

For public videos, Internet Hands can collect official Data API metadata and derive lightweight
signals from public statistics:

- views
- likes
- comments
- engagement actions
- engagement rate per view
- like rate per view
- comment rate per view
- title, description, tags, channel, category, publish time
- duration and status fields returned by the API

Real creator revenue is different. `estimatedRevenue` and related monetary metrics come from the
owner-authorized YouTube Analytics API. Internet Hands exposes those only when the caller has a
valid authorized token.

For videos the caller does not own, the tool may calculate an RPM scenario only when the caller
supplies the RPM assumptions. That output is labeled as a scenario estimate, not reported
creator earnings.

## Video-content analysis architecture

Metadata analysis is only stage one. The intended media pipeline is:

```text
video target
   │
   ├── official metadata
   ├── public thumbnail / preview assets
   ├── authorized captions or caller-supplied transcript
   └── caller-supplied / authorized media file
   │
   ▼
media evidence store
   │
   ├── hashes
   ├── timestamps
   ├── frame references
   ├── transcript segments
   └── source provenance
   │
   ▼
analysis workers
   │
   ├── transcript summarization
   ├── topic/entity extraction
   ├── scene segmentation
   ├── visual-object detection
   ├── OCR on selected frames
   ├── speech/language statistics
   ├── sentiment/tone signals
   └── engagement/statistical analysis
   │
   ▼
normalized VideoIntel record
```

The system should not depend on defeating platform download controls. Full media analysis should
accept caller-provided media, directly public media resources, or provider-authorized sources.
That keeps the analysis layer reusable across YouTube, TikTok, Twitch, uploaded clips, podcasts,
and future providers.

## Routing and fallback

The next router should score candidate collectors using:

1. capability match;
2. whether required credentials are available;
3. whether the data is public or owner-authorized;
4. provider health;
5. recent rate-limit state;
6. expected cost/quota usage;
7. freshness requirements;
8. source quality;
9. whether a raw-web fallback can answer the request without losing important structure.

A provider returning `429`, quota exhaustion, or a transient failure should enter a cooldown and
allow another legitimate source to serve the request where one exists. The router must not rotate
through unrelated accounts or keys merely to evade a provider's quota.

## Endpoint discovery strategy

Safe endpoint discovery should prefer, in order:

1. official API documentation;
2. provider OpenAPI/Swagger descriptions;
3. public protocol specifications such as ActivityPub or AT Protocol;
4. documented public feeds such as RSS/Atom, sitemaps, oEmbed, and JSON-LD/schema.org;
5. public web pages captured through the existing HTTP/browser pipeline;
6. adapters supplied by users for systems they are authorized to access.

This gives Internet Hands huge coverage without making undocumented private endpoints a core
dependency.

## Data model direction

Every normalized intelligence record should eventually contain:

```text
record_id
provider
capability
subject
canonical_url
collected_at
source_endpoint
source_hash
public_or_authorized
raw_capture_ref
normalized_data
derived_signals
confidence
warnings
rate_limit_snapshot
adapter_version
```

Derived claims should point back to evidence. An agent must be able to answer both "what did you
find?" and "where exactly did that come from?"

## Network security

The public-target policy remains mandatory for raw URLs and dynamically selected hosts:

- block localhost and private address space;
- block loopback, link-local, multicast, reserved, and unspecified addresses;
- permit only HTTP/HTTPS;
- re-check redirect targets;
- filter browser subrequests;
- keep response-size and timeout limits;
- keep crawl scope bounded.

For production, add network-level public-only egress enforcement so DNS rebinding cannot turn a
validated public hostname into access to an internal address between DNS validation and connect.

## Control-plane security

v0.3 changes the FastAPI control plane to fail closed by default. Set:

```bash
export INTERNET_HANDS_API_KEY='a-long-random-value'
```

For intentionally unauthenticated trusted local development only:

```bash
export INTERNET_HANDS_ALLOW_UNAUTHENTICATED=1
```

Do not expose arbitrary URL fetching anonymously to the public internet.

## Provider credentials

See `.env.example`. Current optional credentials include:

```text
YOUTUBE_API_KEY
YOUTUBE_ANALYTICS_ACCESS_TOKEN
GITHUB_TOKEN
TWITCH_CLIENT_ID
TWITCH_ACCESS_TOKEN
TIKTOK_ACCESS_TOKEN
REDDIT_ACCESS_TOKEN
```

Tokens are read from environment variables and are not written into provenance records.

## v0.3+ execution roadmap

### P0 — make the fabric reliable

- unified rate-limit state and circuit breakers
- network-level egress enforcement / DNS pinning
- provider error taxonomy
- retry budgets with jitter
- normalized provenance records
- integration tests with mocked provider responses
- API exception mapping so upstream errors become clean 4xx/5xx responses

### P1 — expand intelligence

- YouTube comments and channel upload analysis
- Twitch videos/streams collectors
- TikTok authorized video-list/query collectors
- Mastodon author-feed collector
- Reddit OAuth listing/profile adapters
- GitLab profile/project adapters
- Wikipedia/Wikidata research adapters
- OpenAlex/Crossref research search
- npm/PyPI/crates package intelligence
- RSS/Atom, sitemap, oEmbed, and JSON-LD extractors

### P2 — media intelligence

- `VideoIntel` normalized schema
- transcript ingestion and segmentation
- frame-sampling interface
- pluggable vision/speech analyzers
- thumbnail and scene evidence storage
- per-segment citations/provenance
- creator-owned analytics joins

### P3 — agent-scale fabric

- Postgres backend
- queue-backed distributed workers
- provider capability router
- per-provider concurrency budgets
- endpoint health history
- distributed caching
- query planner across web/API/index sources
- streaming result events
- MCP/agent tool surface

### P4 — operator interface

- dashboard for captures, endpoints, provider health, rate limits, watches, and provenance
- source graph / identity-claim graph
- video-analysis timeline
- saved investigations and reusable collection recipes

The target is not "scrape everything at any cost." The target is an internet subsystem that can
answer broad questions, explain its evidence, route around ordinary provider failures, and keep
working as new public APIs and protocols appear.
