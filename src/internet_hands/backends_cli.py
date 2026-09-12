from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .backends import (
    DEFAULT_BACKEND_ROOT,
    backend_specs,
    backend_status,
    clone_backend,
    playwright_mcp_config,
    sync_default_backends,
)

app = typer.Typer(no_args_is_help=True, help="Curated Internet Hands backend manager.")
console = Console()
RootPath = Annotated[Path, typer.Option("--root")]


def _dump(value) -> None:
    console.print_json(json.dumps(value, default=str))


@app.command("list")
def list_backends():
    """List curated engines and their integration roles/licenses."""
    _dump(
        [
            {
                "name": spec.name,
                "repository": spec.repository,
                "license": spec.license,
                "role": spec.role,
                "integration": spec.integration,
                "clone_by_default": spec.clone_by_default,
                "notes": spec.notes,
            }
            for spec in backend_specs()
        ]
    )


@app.command("status")
def status(
    name: str | None = None,
    root: RootPath = DEFAULT_BACKEND_ROOT,
):
    """Show clone/runtime readiness for one or all curated backends."""
    if name:
        _dump(backend_status(name, root=root))
        return
    _dump([backend_status(spec.name, root=root) for spec in backend_specs()])


@app.command("sync")
def sync(
    name: str = typer.Argument("all"),
    root: RootPath = DEFAULT_BACKEND_ROOT,
    update: bool = typer.Option(True, "--update/--no-update"),
):
    """Clone/update curated backend source and pin exact upstream commits locally."""
    if name == "all":
        _dump(sync_default_backends(root=root, update=update))
        return
    _dump(clone_backend(name, root=root, update=update))


@app.command("playwright-mcp-config")
def playwright_config():
    """Print a portable Microsoft Playwright MCP configuration."""
    _dump(playwright_mcp_config())


if __name__ == "__main__":
    app()
