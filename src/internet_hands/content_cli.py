from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .object_store import S3ObjectStore
from .postgres_store import PostgresCaptureStore

app = typer.Typer(no_args_is_help=True, help="Shared Internet Hands content-store operations.")
console = Console()
ContentPostgresDsn = Annotated[
    str | None,
    typer.Option("--postgres-dsn", envvar="INTERNET_HANDS_CONTENT_POSTGRES_DSN"),
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


def _store(
    postgres_dsn: str | None,
    s3_bucket: str | None,
    s3_prefix: str,
    s3_endpoint: str | None,
    s3_region: str | None,
) -> PostgresCaptureStore:
    dsn = postgres_dsn or os.getenv("INTERNET_HANDS_CONTENT_POSTGRES_DSN")
    bucket = s3_bucket or os.getenv("INTERNET_HANDS_S3_BUCKET")
    if not dsn:
        raise typer.BadParameter("INTERNET_HANDS_CONTENT_POSTGRES_DSN is required")
    if not bucket:
        raise typer.BadParameter("INTERNET_HANDS_S3_BUCKET is required")
    objects = S3ObjectStore(
        bucket=bucket,
        prefix=s3_prefix,
        endpoint_url=s3_endpoint,
        region_name=s3_region,
    )
    return PostgresCaptureStore(dsn, object_store=objects)


@app.command("search")
def search(
    query: Annotated[str, typer.Argument()],
    limit: int = typer.Option(20, min=1, max=200),
    postgres_dsn: ContentPostgresDsn = None,
    s3_bucket: S3Bucket = None,
    s3_prefix: S3Prefix = "internet-hands/objects",
    s3_endpoint: S3Endpoint = None,
    s3_region: S3Region = None,
):
    """Search the shared Postgres full-text document index."""
    store = _store(postgres_dsn, s3_bucket, s3_prefix, s3_endpoint, s3_region)
    _dump([item.model_dump(mode="json") for item in store.search(query, limit=limit)])


@app.command("stats")
def stats(
    postgres_dsn: ContentPostgresDsn = None,
    s3_bucket: S3Bucket = None,
    s3_prefix: S3Prefix = "internet-hands/objects",
    s3_endpoint: S3Endpoint = None,
    s3_region: S3Region = None,
):
    """Show shared capture/document counts."""
    _dump(_store(postgres_dsn, s3_bucket, s3_prefix, s3_endpoint, s3_region).stats())


@app.command("recent")
def recent(
    limit: int = typer.Option(50, min=1, max=1000),
    postgres_dsn: ContentPostgresDsn = None,
    s3_bucket: S3Bucket = None,
    s3_prefix: S3Prefix = "internet-hands/objects",
    s3_endpoint: S3Endpoint = None,
    s3_region: S3Region = None,
):
    """Show recent shared capture metadata."""
    store = _store(postgres_dsn, s3_bucket, s3_prefix, s3_endpoint, s3_region)
    _dump(store.recent_captures(limit=limit))


if __name__ == "__main__":
    app()
