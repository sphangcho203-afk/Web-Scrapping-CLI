from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .frontier import DEFAULT_FRONTIER_DB, FrontierStore
from .hunt import HuntScope, search_seeds
from .postgres_frontier import PostgresFrontier
from .storage import DEFAULT_DB
from .worker import FrontierWorker

app = typer.Typer(no_args_is_help=True, help="Durable Internet Hands crawl fleet control.")
console = Console()
FrontierPath = Annotated[Path, typer.Option("--frontier-db")]
ContentPath = Annotated[Path, typer.Option("--content-db")]
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


def _dump(value) -> None:
    console.print_json(json.dumps(value, default=str))


def _frontier(frontier_db: Path, postgres_dsn: str | None):
    if postgres_dsn:
        return PostgresFrontier(postgres_dsn)
    return FrontierStore(frontier_db)


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


def _worker(
    *,
    worker_id: str | None,
    frontier_db: Path,
    postgres_dsn: str | None,
    content_db: Path,
    backend: str,
    allow_external_network: bool,
    max_depth: int,
    lease_seconds: int,
    respect_robots: bool,
    browser_fallback: bool,
    per_host_delay: float,
) -> FrontierWorker:
    return FrontierWorker(
        worker_id,
        frontier_db=frontier_db,
        postgres_dsn=postgres_dsn,
        content_db=content_db,
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
    postgres_dsn: PostgresDsn = None,
):
    """Lease and process one worker batch."""
    worker = _worker(
        worker_id=worker_id,
        frontier_db=frontier_db,
        postgres_dsn=postgres_dsn,
        content_db=content_db,
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
    postgres_dsn: PostgresDsn = None,
):
    """Process batches until the currently available frontier is empty."""
    worker = _worker(
        worker_id=worker_id,
        frontier_db=frontier_db,
        postgres_dsn=postgres_dsn,
        content_db=content_db,
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
