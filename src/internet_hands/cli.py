from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .crawler import crawl as crawl_site
from .fetcher import (
    extract_links,
    fetch_url,
    health_check,
    inspect_api,
    inspect_download,
    save_capture,
)
from .monitor import monitor_once

app = typer.Typer(no_args_is_help=True, help="Internet Hands — raw internet intelligence.")
console = Console()


def _dump(value) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    console.print_json(json.dumps(value, default=str))


@app.command()
def fetch(
    url: str,
    save: bool = typer.Option(False, "--save", help="Persist manifest and response body."),
    body: bool = typer.Option(False, "--body", help="Print the captured body too."),
    max_bytes: int = typer.Option(8_000_000, min=1, max=50_000_000),
):
    """Fetch one public HTTP(S) resource with raw metadata and hashing."""
    result = asyncio.run(fetch_url(url, include_body=True, max_bytes=max_bytes))
    shown = result if body else result.model_copy(update={"body_text": None, "body_base64": None})
    _dump(shown)
    if save:
        path = save_capture(result)
        console.print(f"[green]saved[/green] {path}")


@app.command()
def links(url: str):
    """Extract normalized HTTP(S) links from a page."""
    result = asyncio.run(fetch_url(url, include_body=True))
    _dump(extract_links(result))


@app.command(name="api")
def api_command(url: str):
    """Inspect an API endpoint and parse JSON when possible."""
    _dump(asyncio.run(inspect_api(url)))


@app.command()
def health(url: str):
    """Check reachability, status, latency, and content type."""
    _dump(asyncio.run(health_check(url)))


@app.command()
def crawl(
    url: str,
    max_pages: int = typer.Option(25, min=1, max=500),
    respect_robots: bool = typer.Option(True, "--respect-robots/--ignore-robots"),
    delay: float = typer.Option(0.35, min=0.0, max=60.0),
):
    """Bounded same-origin crawl with deduplication."""
    result = asyncio.run(
        crawl_site(url, max_pages=max_pages, delay_seconds=delay, respect_robots=respect_robots)
    )
    table = Table("status", "links", "url / error")
    for page in result.pages:
        table.add_row(str(page.status_code or "-"), str(page.links_found), page.error or page.url)
    console.print(table)


@app.command()
def monitor(
    url: str,
    state: Path = typer.Option(Path(".internet-hands/state.json"), "--state"),
):
    """Capture a hash snapshot and report whether the resource changed."""
    _dump(asyncio.run(monitor_once(url, state)))


@app.command(name="download-info")
def download_info(url: str):
    """Inspect a public download target without downloading the full file."""
    _dump(asyncio.run(inspect_download(url)))


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8787, min=1, max=65535),
):
    """Run the local FastAPI service."""
    import uvicorn

    uvicorn.run("internet_hands.api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
