from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console

from .discovery import discover_public_interfaces

app = typer.Typer(
    no_args_is_help=True,
    help="Discover published machine-readable interfaces on a public website.",
)
console = Console()


@app.command()
def inspect(
    url: str,
    probe_openapi: bool = typer.Option(
        False,
        "--probe-openapi",
        help="Also check a small fixed list of common OpenAPI publication paths.",
    ),
):
    """Inspect a page, robots.txt, and optional OpenAPI publication paths."""
    result = asyncio.run(discover_public_interfaces(url, probe_openapi=probe_openapi))
    console.print_json(json.dumps(result, default=str))


if __name__ == "__main__":
    app()
