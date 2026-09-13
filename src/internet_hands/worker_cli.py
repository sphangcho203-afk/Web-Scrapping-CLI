from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Annotated

import typer

from .frontier import DEFAULT_FRONTIER_DB
from .storage import DEFAULT_DB, DEFAULT_OBJECTS
from .telemetry import DEFAULT_TELEMETRY_DB, PostgresTelemetry, SqliteTelemetry
from .worker import FrontierWorker

app = typer.Typer(add_completion=False, help="Run a long-lived Internet Hands fleet worker.")


def _path_env(name: str, default: Path) -> Path:
    return Path(os.getenv(name, str(default)))


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    return value if value else None


async def _serve(
    *,
    worker: FrontierWorker,
    batch_size: int,
    idle_seconds: float,
) -> None:
    while True:
        result = await worker.run_once(batch_size=batch_size)
        if result.leased == 0:
            await asyncio.sleep(idle_seconds)


@app.callback(invoke_without_command=True)
def main(
    worker_id: Annotated[str | None, typer.Option("--worker-id")] = None,
    backend: Annotated[str, typer.Option("--backend")] = "native",
    batch_size: Annotated[int, typer.Option(min=1, max=256)] = 16,
    idle_seconds: Annotated[float, typer.Option(min=0.1, max=300.0)] = 5.0,
    max_depth: Annotated[int, typer.Option(min=0, max=50)] = 5,
    lease_seconds: Annotated[int, typer.Option(min=10, max=3600)] = 120,
    per_host_delay: Annotated[float, typer.Option(min=0.0, max=3600.0)] = 0.35,
    allow_external_network: Annotated[
        bool,
        typer.Option("--allow-external-network"),
    ] = False,
    browser_fallback: Annotated[bool, typer.Option("--browser-fallback")] = False,
    respect_robots: Annotated[
        bool,
        typer.Option("--respect-robots/--ignore-robots"),
    ] = True,
):
    """Continuously lease and process crawl jobs."""
    telemetry_postgres_dsn = _optional_env("INTERNET_HANDS_TELEMETRY_POSTGRES_DSN")
    telemetry = (
        PostgresTelemetry(telemetry_postgres_dsn)
        if telemetry_postgres_dsn
        else SqliteTelemetry(_path_env("INTERNET_HANDS_TELEMETRY_DB", DEFAULT_TELEMETRY_DB))
    )
    worker = FrontierWorker(
        worker_id,
        frontier_db=_path_env("INTERNET_HANDS_FRONTIER_DB", DEFAULT_FRONTIER_DB),
        postgres_dsn=_optional_env("INTERNET_HANDS_POSTGRES_DSN"),
        content_db=_path_env("INTERNET_HANDS_DB", DEFAULT_DB),
        content_postgres_dsn=_optional_env("INTERNET_HANDS_CONTENT_POSTGRES_DSN"),
        objects_root=_path_env("INTERNET_HANDS_OBJECTS", DEFAULT_OBJECTS),
        s3_bucket=_optional_env("INTERNET_HANDS_S3_BUCKET"),
        s3_prefix=os.getenv("INTERNET_HANDS_S3_PREFIX", "internet-hands/objects"),
        s3_endpoint_url=_optional_env("INTERNET_HANDS_S3_ENDPOINT_URL"),
        s3_region=_optional_env("AWS_REGION"),
        telemetry=telemetry,
        backend=backend,
        allow_external_network=allow_external_network,
        max_depth=max_depth,
        lease_seconds=lease_seconds,
        respect_robots=respect_robots,
        browser_fallback=browser_fallback,
        per_host_delay=per_host_delay,
    )
    try:
        asyncio.run(_serve(worker=worker, batch_size=batch_size, idle_seconds=idle_seconds))
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    app()
