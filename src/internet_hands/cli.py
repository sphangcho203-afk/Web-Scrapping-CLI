from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .browser import render_page
from .crawler import crawl as crawl_site
from .endpoints import Capability, endpoint_catalog
from .fetcher import (
    extract_links,
    fetch_url,
    health_check,
    inspect_api,
    inspect_download,
    save_capture,
)
from .intel import (
    bluesky_feed,
    bluesky_profile,
    github_repositories,
    github_user,
    hackernews_item,
    mastodon_profile,
    public_username_scan,
    tiktok_authorized_profile,
    twitch_user,
    youtube_channel,
    youtube_owner_analytics,
    youtube_revenue_scenario,
    youtube_video,
)
from .monitor import monitor_once
from .pipeline import index_crawl, index_url, run_due_watches
from .storage import DEFAULT_DB, Store

app = typer.Typer(no_args_is_help=True, help="Internet Hands — public internet intelligence.")
watch_app = typer.Typer(no_args_is_help=True, help="Persistent web monitoring jobs.")
intel_app = typer.Typer(no_args_is_help=True, help="Provider-backed public intelligence.")
app.add_typer(watch_app, name="watch")
app.add_typer(intel_app, name="intel")
console = Console()
DEFAULT_STATE = Path(".internet-hands/state.json")
DbPath = Annotated[Path, typer.Option("--db")]
StatePath = Annotated[Path, typer.Option("--state")]
CapabilityOption = Annotated[Capability | None, typer.Option("--capability")]
StartDateOption = Annotated[date, typer.Option("--start")]
EndDateOption = Annotated[date, typer.Option("--end")]


def _dump(value) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, list):
        value = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in value
        ]
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
def index(
    url: str,
    db: DbPath = DEFAULT_DB,
):
    """Fetch, extract, persist, and full-text index one public page."""
    _dump(asyncio.run(index_url(url, db_path=db)))


@app.command(name="index-crawl")
def index_crawl_command(
    url: str,
    db: DbPath = DEFAULT_DB,
    max_pages: int = typer.Option(25, min=1, max=500),
    delay: float = typer.Option(0.35, min=0.0, max=60.0),
    respect_robots: bool = typer.Option(True, "--respect-robots/--ignore-robots"),
):
    """Crawl a public origin and add extracted pages to the local search index."""
    result = asyncio.run(
        index_crawl(
            url,
            db_path=db,
            max_pages=max_pages,
            delay_seconds=delay,
            respect_robots=respect_robots,
        )
    )
    _dump(result)


@app.command()
def search(
    query: str,
    db: DbPath = DEFAULT_DB,
    limit: int = typer.Option(20, min=1, max=200),
):
    """Search indexed page text with SQLite FTS5."""
    _dump(Store(db).search(query, limit=limit))


@app.command()
def export(
    output: Path,
    db: DbPath = DEFAULT_DB,
):
    """Export indexed captures to newline-delimited JSON."""
    count = Store(db).export_jsonl(output)
    console.print(f"[green]exported[/green] {count} documents -> {output}")


@app.command()
def browser(
    url: str,
    body: bool = typer.Option(False, "--body", help="Print rendered HTML too."),
):
    """Render a public page with the optional Playwright browser worker."""
    result = asyncio.run(render_page(url))
    if not body:
        result = result.model_copy(update={"html": ""})
    _dump(result)


@app.command()
def monitor(
    url: str,
    state: StatePath = DEFAULT_STATE,
):
    """Capture a hash snapshot and report whether the resource changed."""
    _dump(asyncio.run(monitor_once(url, state)))


@watch_app.command("add")
def watch_add(
    url: str,
    every: int = typer.Option(3600, "--every", min=60, help="Interval in seconds."),
    db: DbPath = DEFAULT_DB,
):
    """Create or update a persistent monitoring job."""
    _dump(Store(db).add_watch(url, every))


@watch_app.command("list")
def watch_list(db: DbPath = DEFAULT_DB):
    """List persistent monitoring jobs."""
    _dump(Store(db).list_watches())


@watch_app.command("run")
def watch_run(
    db: DbPath = DEFAULT_DB,
    limit: int = typer.Option(100, min=1, max=1000),
):
    """Run monitoring jobs that are currently due."""
    _dump(asyncio.run(run_due_watches(db_path=db, limit=limit)))


@app.command(name="download-info")
def download_info(url: str):
    """Inspect a public download target without downloading the full file."""
    _dump(asyncio.run(inspect_download(url)))


@app.command("endpoints")
def endpoints_command(
    provider: str | None = typer.Option(None, "--provider"),
    capability: CapabilityOption = None,
    ready_only: bool = typer.Option(False, "--ready-only"),
):
    """List the built-in official/public endpoint capability catalog."""
    items = endpoint_catalog(
        provider=provider,
        capability=capability,
        ready_only=ready_only,
    )
    _dump(
        [
            {
                "provider": item.provider,
                "name": item.name,
                "capability": item.capability.value,
                "method": item.method,
                "url": item.url,
                "auth": item.auth.value,
                "env": list(item.env),
                "ready": item.ready,
                "public_data": item.public_data,
                "notes": item.notes,
            }
            for item in items
        ]
    )


@intel_app.command("youtube-video")
def intel_youtube_video(target: str):
    """Collect a YouTube video's public metadata, statistics, and derived engagement."""
    _dump(asyncio.run(youtube_video(target)))


@intel_app.command("youtube-channel")
def intel_youtube_channel(target: str):
    """Collect a YouTube channel by channel ID or @handle."""
    _dump(asyncio.run(youtube_channel(target)))


@intel_app.command("youtube-owner-analytics")
def intel_youtube_owner_analytics(
    start: StartDateOption,
    end: EndDateOption,
    video: str | None = typer.Option(None, "--video"),
    currency: str = typer.Option("USD", "--currency"),
):
    """Read owner-authorized YouTube Analytics, including revenue metrics."""
    _dump(
        asyncio.run(
            youtube_owner_analytics(
                start,
                end,
                video_id=video,
                currency=currency,
            )
        )
    )


@intel_app.command("youtube-revenue-scenario")
def intel_youtube_revenue_scenario(
    views: int = typer.Argument(..., min=0),
    rpm_low: float = typer.Option(..., "--rpm-low", min=0),
    rpm_high: float = typer.Option(..., "--rpm-high", min=0),
    currency: str = typer.Option("USD", "--currency"),
):
    """Estimate a range from caller-supplied RPM assumptions."""
    _dump(
        youtube_revenue_scenario(
            views,
            rpm_low=rpm_low,
            rpm_high=rpm_high,
            currency=currency,
        )
    )


@intel_app.command("github-user")
def intel_github_user(username: str):
    """Collect a public GitHub profile."""
    _dump(asyncio.run(github_user(username)))


@intel_app.command("github-repos")
def intel_github_repositories(
    username: str,
    limit: int = typer.Option(100, min=1, max=100),
):
    """Collect a user's public GitHub repositories."""
    _dump(asyncio.run(github_repositories(username, limit=limit)))


@intel_app.command("bluesky-profile")
def intel_bluesky_profile(actor: str):
    """Collect a public Bluesky profile."""
    _dump(asyncio.run(bluesky_profile(actor)))


@intel_app.command("bluesky-feed")
def intel_bluesky_feed(
    actor: str,
    limit: int = typer.Option(50, min=1, max=100),
):
    """Collect a public Bluesky author feed."""
    _dump(asyncio.run(bluesky_feed(actor, limit=limit)))


@intel_app.command("hn-item")
def intel_hackernews_item(item_id: int):
    """Collect one public Hacker News item."""
    _dump(asyncio.run(hackernews_item(item_id)))


@intel_app.command("mastodon-profile")
def intel_mastodon_profile(instance: str, account: str):
    """Collect a public Mastodon profile from an explicit instance."""
    _dump(asyncio.run(mastodon_profile(instance, account)))


@intel_app.command("twitch-user")
def intel_twitch_user(login: str):
    """Collect Twitch user metadata using configured app credentials."""
    _dump(asyncio.run(twitch_user(login)))


@intel_app.command("tiktok-me")
def intel_tiktok_me():
    """Collect the profile of the TikTok user who explicitly authorized the token."""
    _dump(asyncio.run(tiktok_authorized_profile()))


@intel_app.command("username")
def intel_username(username: str):
    """Check an exact public handle across selected public providers."""
    _dump(asyncio.run(public_username_scan(username)))


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
