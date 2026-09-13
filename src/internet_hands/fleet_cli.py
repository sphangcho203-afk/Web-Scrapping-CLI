from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .frontier import DEFAULT_FRONTIER_DB, FrontierStore
from .hunt import HuntScope, search_seeds
from .postgres_frontier import PostgresFrontier
from .storage import DEFAULT_DB, DEFAULT_OBJECTS
from .telemetry import DEFAULT_TELEMETRY_DB, PostgresTelemetry, SqliteTelemetry
from .worker import FrontierWorker

app = typer.Typer(no_args_is_help=True, help="Durable Internet Hands crawl fleet control.")
console = Console()
FrontierPath = Annotated[Path, typer.Option("--frontier-db")]
ContentPath = Annotated[Path, typer.Option("--content-db")]
ObjectsPath = Annotated[Path, typer.Option("--objects-root")]
TelemetryPath = Annotated[Path, typer.Option("--telemetry-db")]
SeedUrls = Annotated[list[str] | None, typer.Argument()]
QueryOption = Annotated[str | None, typer.Option("--query")]
SearchCount = Annotated[int, typer.Option(min=1, max=20)]
ScopeOption = Annotated[HuntScope, typer.Option("--scope")]
PriorityOption = Annotated[int, typer.Option("--priority")]
MaxAttempts = Annotated[int, typer.Option(min=1, max=50)]
PostgresDsn = Annotated[
    str | None,
    typer.Option("--postgres-dsn", envvar="INTERNET_HANDS_POSTGRES_DSN"),
]
ContentPostgresDsn = Annotated[
    str | None,
    typer.Option("--content-postgres-dsn", envvar="INTERNET_HANDS_CONTENT_POSTGRES_DSN"),
]
TelemetryPostgresDsn = Annotated[
    str | None,
    typer.Option("--telemetry-postgres-dsn", envvar="INTERNET_HANDS_TELEMETRY_POSTGRES_DSN"),
]
S3Bucket = Annotated[
    str | None,
    typer.Option("--s3-bucket", envvar="INTERNET_HANDS_S3_BUCKET"),
]
S3Prefix = Annotated[
    str,
    typer.Option("--s3-prefix", envvar="INTERNET_HANDS_S3_PREFIX"),
]
S3Endpoint = Annotated[
    str | None,
    typer.Option("--s3-endpoint", envvar="INTERNET_HANDS_S3_ENDPOINT_URL"),
]
S3Region = Annotated[
    str | None,
    typer.Option("--s3-region", envvar="AWS_REGION"),
]


def _dump(value) -> None:
    console.print_json(json.dumps(value, default=str))


def _frontier(frontier_db: Path, postgres_dsn: str | None):
    if postgres_dsn:
        return PostgresFrontier(postgres_dsn)
    return FrontierStore(frontier_db)


def _telemetry(telemetry_db: Path, postgres_dsn: str | None):
    if postgres_dsn:
        return PostgresTelemetry(postgres_dsn)
    return SqliteTelemetry(telemetry_db)


@app.command("seed")
def seed(
    urls: SeedUrls = None,
    query: QueryOption = None,
    search_count: SearchCount = 10,
    scope: ScopeOption = HuntScope.ORIGIN,
    priority: PriorityOption = 0,
    max_attempts: MaxAttempts = 4,
    frontier_db: FrontierPath = DEFAULT_FRONTIER_DB,
    postgres_dsn: PostgresDsn = None,
):
    """Seed one or more URLs, optionally adding Brave search results."""
    targets = list(urls or [])
    if query:
        targets.extend(asyncio.run(search_seeds(query, count=search_count)))
    if not targets:
        raise typer.BadParameter("Provide URL arguments or --query")
    frontier = _frontier(frontier_db, postgres_dsn)
    added = 0
    for target in targets:
        try:
            added += int(
                frontier.enqueue(
                    target,
                    root_url=target,
                    scope=scope.value,
                    priority=priority,
                    max_attempts=max_attempts,
                )
            )
        except (ValueError, OSError) as exc:
            console.print(f"Skipped {target}: {exc}")
    _dump({"submitted": len(targets), "added": added, "stats": frontier.stats()})


@app.command("stats")
def stats(
    frontier_db: FrontierPath = DEFAULT_FRONTIER_DB,
    postgres_dsn: PostgresDsn = None,
):
    """Show durable frontier state counts."""
    _dump(_frontier(frontier_db, postgres_dsn).stats())


@app.command("events")
def events(
    after_id: int = typer.Option(0, min=0),
    limit: int = typer.Option(100, min=1, max=1000),
    follow: bool = typer.Option(False, "--follow"),
    poll_seconds: float = typer.Option(1.0, min=0.1, max=60.0),
    telemetry_db: TelemetryPath = DEFAULT_TELEMETRY_DB,
    telemetry_postgres_dsn: TelemetryPostgresDsn = None,
):
    """Read or follow durable worker telemetry as JSON lines."""
    sink = _telemetry(telemetry_db, telemetry_postgres_dsn)
    cursor = after_id
    while True:
        batch = sink.list_events(after_id=cursor, limit=limit)
        for event in batch:
            console.print_json(json.dumps(dataclasses.asdict(event), default=str))
            cursor = event.id
        if not follow:
            break
        if not batch:
            time.sleep(poll_seconds)


def _worker(
    *,
    worker_id: str | None,
    frontier_db: Path,
    postgres_dsn: str | None,
    content_db: Path,
    content_postgres_dsn: str | None,
    objects_root: Path,
    s3_bucket: str | None,
    s3_prefix: str,
    s3_endpoint: str | None,
    s3_region: str | None,
    telemetry_db: Path,
    telemetry_postgres_dsn: str | None,
    backend: str,
    allow_external_network: bool,
    max_depth: int,
    lease_seconds: int,
    respect_robots: bool,
    browser_fallback: bool,
    per_host_delay: float,
) -> FrontierWorker:
    telemetry = _telemetry(telemetry_db, telemetry_postgres_dsn)
    return FrontierWorker(
        worker_id,
        frontier_db=frontier_db,
        postgres_dsn=postgres_dsn,
        content_db=content_db,
        content_postgres_dsn=content_postgres_dsn,
        objects_root=objects_root,
        s3_bucket=s3_bucket,
        s3_prefix=s3_prefix,
        s3_endpoint_url=s3_endpoint,
        s3_region=s3_region,
        telemetry=telemetry,
        backend=backend,
        allow_external_network=allow_external_network,
        max_depth=max_depth,
        lease_seconds=lease_seconds,
        respect_robots=respect_robots,
        browser_fallback=browser_fallback,
        per_host_delay=per_host_delay,
    )


@app.command("run-once")
def run_once(
    worker_id: str | None = typer.Option(None, "--worker-id"),
    batch_size: int = typer.Option(8, min=1, max=256),
    backend: str = typer.Option("native", "--backend"),
    allow_external_network: bool = typer.Option(False, "--allow-external-network"),
    max_depth: int = typer.Option(5, min=0, max=50),
    lease_seconds: int = typer.Option(120, min=10, max=3600),
    respect_robots: bool = typer.Option(True, "--respect-robots/--ignore-robots"),
    browser_fallback: bool = typer.Option(False, "--browser-fallback"),
    per_host_delay: float = typer.Option(0.35, min=0.0, max=3600.0),
    frontier_db: FrontierPath = DEFAULT_FRONTIER_DB,
    content_db: ContentPath = DEFAULT_DB,
    objects_root: ObjectsPath = DEFAULT_OBJECTS,
    postgres_dsn: PostgresDsn = None,
    content_postgres_dsn: ContentPostgresDsn = None,
    telemetry_db: TelemetryPath = DEFAULT_TELEMETRY_DB,
    telemetry_postgres_dsn: TelemetryPostgresDsn = None,
    s3_bucket: S3Bucket = None,
    s3_prefix: S3Prefix = "internet-hands/objects",
    s3_endpoint: S3Endpoint = None,
    s3_region: S3Region = None,
):
    """Lease and process one worker batch."""
    worker = _worker(
        worker_id=worker_id,
        frontier_db=frontier_db,
        postgres_dsn=postgres_dsn,
        content_db=content_db,
        content_postgres_dsn=content_postgres_dsn,
        objects_root=objects_root,
        s3_bucket=s3_bucket,
        s3_prefix=s3_prefix,
        s3_endpoint=s3_endpoint,
        s3_region=s3_region,
        telemetry_db=telemetry_db,
        telemetry_postgres_dsn=telemetry_postgres_dsn,
        backend=backend,
        allow_external_network=allow_external_network,
        max_depth=max_depth,
        lease_seconds=lease_seconds,
        respect_robots=respect_robots,
        browser_fallback=browser_fallback,
        per_host_delay=per_host_delay,
    )
    result = asyncio.run(worker.run_once(batch_size=batch_size))
    _dump(dataclasses.asdict(result))


@app.command("drain")
def drain(
    worker_id: str | None = typer.Option(None, "--worker-id"),
    batch_size: int = typer.Option(8, min=1, max=256),
    max_batches: int = typer.Option(1000, min=1, max=1_000_000),
    backend: str = typer.Option("native", "--backend"),
    allow_external_network: bool = typer.Option(False, "--allow-external-network"),
    max_depth: int = typer.Option(5, min=0, max=50),
    lease_seconds: int = typer.Option(120, min=10, max=3600),
    respect_robots: bool = typer.Option(True, "--respect-robots/--ignore-robots"),
    browser_fallback: bool = typer.Option(False, "--browser-fallback"),
    per_host_delay: float = typer.Option(0.35, min=0.0, max=3600.0),
    frontier_db: FrontierPath = DEFAULT_FRONTIER_DB,
    content_db: ContentPath = DEFAULT_DB,
    objects_root: ObjectsPath = DEFAULT_OBJECTS,
    postgres_dsn: PostgresDsn = None,
    content_postgres_dsn: ContentPostgresDsn = None,
    telemetry_db: TelemetryPath = DEFAULT_TELEMETRY_DB,
    telemetry_postgres_dsn: TelemetryPostgresDsn = None,
    s3_bucket: S3Bucket = None,
    s3_prefix: S3Prefix = "internet-hands/objects",
    s3_endpoint: S3Endpoint = None,
    s3_region: S3Region = None,
):
    """Process batches until the currently available frontier is empty."""
    worker = _worker(
        worker_id=worker_id,
        frontier_db=frontier_db,
        postgres_dsn=postgres_dsn,
        content_db=content_db,
        content_postgres_dsn=content_postgres_dsn,
        objects_root=objects_root,
        s3_bucket=s3_bucket,
        s3_prefix=s3_prefix,
        s3_endpoint=s3_endpoint,
        s3_region=s3_region,
        telemetry_db=telemetry_db,
        telemetry_postgres_dsn=telemetry_postgres_dsn,
        backend=backend,
        allow_external_network=allow_external_network,
        max_depth=max_depth,
        lease_seconds=lease_seconds,
        respect_robots=respect_robots,
        browser_fallback=browser_fallback,
        per_host_delay=per_host_delay,
    )
    results = asyncio.run(worker.drain(batch_size=batch_size, max_batches=max_batches))
    _dump(
        {
            "batches": len(results),
            "leased": sum(item.leased for item in results),
            "completed": sum(item.completed for item in results),
            "retried": sum(item.retried for item in results),
            "dead": sum(item.dead for item in results),
            "discovered": sum(item.discovered for item in results),
            "browser_pages": sum(item.browser_pages for item in results),
            "last": dataclasses.asdict(results[-1]) if results else None,
        }
    )


if __name__ == "__main__":
    app()
