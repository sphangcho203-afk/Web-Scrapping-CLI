from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .exports import export_parquet, export_warc
from .storage import DEFAULT_DB

app = typer.Typer(no_args_is_help=True, help="Export Internet Hands capture datasets.")
console = Console()
DbPath = Annotated[Path, typer.Option("--db")]


def _done(kind: str, target: Path, count: int) -> None:
    console.print_json(
        json.dumps(
            {
                "format": kind,
                "target": str(target),
                "records": count,
            }
        )
    )


@app.command("warc")
def warc(
    target: Path = typer.Argument(...),
    db: DbPath = DEFAULT_DB,
):
    """Export captures to WARC/1.1; use a .gz suffix for gzip compression."""
    _done("warc", target, export_warc(db, target))


@app.command("parquet")
def parquet(
    target: Path = typer.Argument(...),
    db: DbPath = DEFAULT_DB,
):
    """Export normalized documents to compressed Parquet."""
    _done("parquet", target, export_parquet(db, target))


if __name__ == "__main__":
    app()
