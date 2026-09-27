# Runtime Stability v7

This layer hardens OpenCrawl's execution and control planes without changing the public
Tool Mesh contract.

## Provider bulkheads

Every Tool Mesh provider has an independent concurrency semaphore. The global default is
controlled by `OPENCRAWL_PROVIDER_MAX_CONCURRENCY` and can be overridden per provider with
`OPENCRAWL_PROVIDER_MAX_CONCURRENCY_<PROVIDER>`.

A saturated provider therefore queues only work targeting that provider; it cannot consume
the full batch concurrency of unrelated providers.

## Hard execution deadlines

`timeout_seconds` is now a wall-clock budget for the entire provider execution loop rather
than a fresh timeout for every retry. Queue time, upstream execution, and retry delay all
consume that same budget. A retry is skipped when its delay would exceed the remaining
deadline.

Provider status, search, and descriptor discovery are separately bounded by
`OPENCRAWL_PROVIDER_DISCOVERY_TIMEOUT_SECONDS`.

## Health isolation

Deep semantic capability checks use
`OPENCRAWL_HEALTH_CAPABILITY_TIMEOUT_SECONDS`. One hanging provider/capability is reported
as unavailable instead of hanging the full health endpoint.

The MCP health contract is additive-safe: required core tools must exist with unique names
and schemas, while newly added tools no longer make the service unhealthy merely because
the total tool count changed.

## Control database fail-fast

Control-plane and shared-reliability Postgres connections use
`OPENCRAWL_DB_CONNECT_TIMEOUT_SECONDS`, bounded to 1–30 seconds.

## Concurrency admission control

Plan `concurrent_limit` is now enforced inside the wallet/reservation transaction. The
wallet row acts as the per-user serialization point, so concurrent reservations cannot
race past the configured limit.

## Settlement finality

A usage event can transition out of `reserved` only once. Later duplicate completion,
cancellation, timeout, or abandoned-worker callbacks return the already-settled charge
without rewriting terminal status or wallet metadata.

The MCP gateway also tracks uncaught application failures and cancellations explicitly so
a crash before an HTTP error is emitted cannot be finalized as `ok`.

## Intended merge order

This branch is stacked after provider-search-games v6:

1. provider reliability v5
2. provider search + games v6
3. runtime stability v7

No deployment-specific configuration is changed by this branch.
