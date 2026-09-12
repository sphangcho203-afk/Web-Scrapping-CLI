from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console

from .openapi import discover_openapi

app = typer.Typer(no_args_is_help=True, help="Discover read-only operations from public OpenAPI specs.")
console = Console()


@app.command()
def discover(
    spec_url: str,
    max_bytes: int = typer.Option(10_000_000, min=1, max=50_000_000),
):
    """Fetch a public OpenAPI JSON/YAML document and inventory GET/HEAD operations."""
    result = asyncio.run(discover_openapi(spec_url, max_bytes=max_bytes))
    console.print_json(json.dumps(result, default=str))


if __name__ == "__main__":
    app()
