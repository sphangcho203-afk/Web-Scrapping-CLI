from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .hunt import HuntScope, hunt, search_seeds
from .storage import DEFAULT_DB

app = typer.Typer(no_args_is_help=True, help="Search-seeded public internet hunt and crawl.")
console = Console()

SeedOption = Annotated[list[str] | None, typer.Option("--seed", help="Seed URL; repeatable.")]
QueryOption = Annotated[str | None, typer.Option("--query", help="Seed from Brave web search.")]
ScopeOption = Annotated[HuntScope, typer.Option("--scope")]
DbPath = Annotated[Path, typer.Option("--db")]


def _dump(value) -> None:
    console.print_json(json.dumps(value, default=str))


@app.command("run")
def run_hunt(
    seed: SeedOption = None,
    query: QueryOption = None,
    scope: ScopeOption = HuntScope.ORIGIN,
    max_pages: int = typer.Option(100, min=1, max=5000),
    max_depth: int = typer.Option(3, min=0, max=12),
    max_domains: int = typer.Option(20, min=1, max=500),
    concurrency: int = typer.Option(8, min=1, max=64),
    per_host_delay: float = typer.Option(0.35, min=0.0, max=60.0),
    search_count: int = typer.Option(10, min=1, max=20),
    index: bool = typer.Option(True, "--index/--no-index"),
    respect_robots: bool = typer.Option(True, "--respect-robots/--ignore-robots"),
    db: DbPath = DEFAULT_DB,
):
    """Search and/or crawl bounded public-web sources into the Internet Hands index."""
    seeds = list(seed or [])
    if query:
        seeds.extend(asyncio.run(search_seeds(query, count=search_count)))
    if not seeds:
        raise typer.BadParameter("Provide at least one --seed or --query")

    result = asyncio.run(
        hunt(
            seeds,
            scope=scope,
            max_pages=max_pages,
            max_depth=max_depth,
            max_domains=max_domains,
            concurrency=concurrency,
            per_host_delay=per_host_delay,
            respect_robots=respect_robots,
            index=index,
            db_path=db,
        )
    )
    _dump(result)


if __name__ == "__main__":
    app()
