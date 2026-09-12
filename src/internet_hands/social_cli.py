from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console

from .social import (
    bluesky_search_posts,
    mastodon_statuses,
    tiktok_authorized_videos,
    twitch_streams,
    twitch_videos,
    youtube_channel_videos,
    youtube_comments,
    youtube_search,
)

app = typer.Typer(no_args_is_help=True, help="Social/public video intelligence collectors.")
console = Console()


def _print(value) -> None:
    console.print_json(json.dumps(value, default=str))


@app.command("youtube-search")
def youtube_search_command(query: str, limit: int = typer.Option(25, min=1, max=50)):
    _print(asyncio.run(youtube_search(query, limit=limit)))


@app.command("youtube-comments")
def youtube_comments_command(video: str, limit: int = typer.Option(100, min=1, max=500)):
    _print(asyncio.run(youtube_comments(video, limit=limit)))


@app.command("youtube-channel-videos")
def youtube_channel_videos_command(
    channel: str,
    limit: int = typer.Option(50, min=1, max=500),
):
    _print(asyncio.run(youtube_channel_videos(channel, limit=limit)))


@app.command("bluesky-search")
def bluesky_search_command(query: str, limit: int = typer.Option(50, min=1, max=100)):
    _print(asyncio.run(bluesky_search_posts(query, limit=limit)))


@app.command("mastodon-statuses")
def mastodon_statuses_command(
    instance: str,
    account_id: str,
    limit: int = typer.Option(40, min=1, max=40),
):
    _print(asyncio.run(mastodon_statuses(instance, account_id, limit=limit)))


@app.command("twitch-videos")
def twitch_videos_command(user_id: str, limit: int = typer.Option(50, min=1, max=100)):
    _print(asyncio.run(twitch_videos(user_id, limit=limit)))


@app.command("twitch-streams")
def twitch_streams_command(
    user_login: str | None = typer.Option(None, "--user-login"),
    limit: int = typer.Option(20, min=1, max=100),
):
    _print(asyncio.run(twitch_streams(user_login=user_login, limit=limit)))


@app.command("tiktok-videos")
def tiktok_videos_command(limit: int = typer.Option(20, min=1, max=20)):
    _print(asyncio.run(tiktok_authorized_videos(limit=limit)))


if __name__ == "__main__":
    app()
