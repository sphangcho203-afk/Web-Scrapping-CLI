from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console

from .web_search import SearchKind, brave_search

app = typer.Typer(no_args_is_help=True, help="Broad public web discovery through configured search APIs.")
console = Console()


@app.command()
def search(
    query: str,
    kind: SearchKind = SearchKind.WEB,
    count: int = 10,
    country: str | None = None,
    language: str | None = None,
    freshness: str | None = None,
):
    """Search the public web with Brave Search using strict safe-search defaults."""
    result = asyncio.run(
        brave_search(
            query,
            kind=kind,
            count=count,
            country=country,
            language=language,
            freshness=freshness,
        )
    )
    console.print_json(json.dumps(result, default=str))


if __name__ == "__main__":
    app()
