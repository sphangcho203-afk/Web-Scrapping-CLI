# Architecture

Internet Hands is split into layers so platform-specific collectors do not need to reimplement network capture, provenance, or policy.

## Core layers

1. **Policy** — validates target URLs, blocks non-public address space, and applies bounded-request rules.
2. **Fetcher** — performs HTTP(S) requests and records final URL, status, headers, byte length, SHA-256, capture time, and body.
3. **Parsers** — derive structured information such as normalized links without discarding the raw capture.
4. **Crawler** — breadth-first same-origin traversal with deduplication, delay, and optional robots.txt handling.
5. **Monitor** — compares cryptographic fingerprints across checks.
6. **Artifacts** — persists manifests and bodies for reproducibility.
7. **Interfaces** — CLI today, local FastAPI service today, dashboard/agent adapters later.

## Planned worker architecture

```text
                 ┌──────────────┐
                 │ Dashboard/UI │
                 └──────┬───────┘
                        │
CLI ───────┐       ┌────▼─────┐       API clients
           ├──────►│ Control  │◄──────────┘
Agents ────┘       │   API    │
                   └────┬─────┘
                        │ jobs
                 ┌──────▼──────┐
                 │ Queue / DB  │
                 └───┬─────┬───┘
                     │     │
          ┌──────────▼┐   ┌▼─────────────┐
          │ HTTP pool │   │ Browser pool │
          └─────┬─────┘   └──────┬───────┘
                │                │
                └──────┬─────────┘
                       ▼
               Artifact + index store
```

## Adapter SDK concept

A platform adapter should declare:

- accepted public URL patterns;
- auth requirements, if any;
- rate-limit policy;
- fetch strategy (`http`, `api`, or isolated browser worker);
- parser/extractor functions;
- normalized output schema;
- provenance pointers back to raw captures.

Adapters should never hide the underlying source response.

## Security boundaries

The API is intended to be self-hosted. A production deployment should add authentication, per-user quotas, egress restrictions, DNS rebinding defenses, observability, and isolated browser workers. Never expose an unrestricted arbitrary-URL fetch endpoint to the public internet.
