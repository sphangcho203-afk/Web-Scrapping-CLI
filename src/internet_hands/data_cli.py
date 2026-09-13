from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console

from .public_data import (
    crates_package,
    crossref_search,
    gitlab_user,
    npm_package,
    openalex_search,
    pypi_package,
    wikidata_search,
    wikipedia_page,
    wikipedia_search,
)

app = typer.Typer(no_args_is_help=True, help="Research, package, and public-data intelligence.")
console = Console()


def _print(value) -> None:
    console.print_json(json.dumps(value, default=str))


@app.command("wiki-search")
def wikipedia_search_command(
    query: str,
    language: str = typer.Option("en", "--language"),
    limit: int = typer.Option(10, min=1, max=50),
):
    _print(asyncio.run(wikipedia_search(query, language=language, limit=limit)))


@app.command("wiki-page")
def wikipedia_page_command(
    title: str,
    language: str = typer.Option("en", "--language"),
):
    _print(asyncio.run(wikipedia_page(title, language=language)))


@app.command("wikidata")
def wikidata_search_command(
    query: str,
    language: str = typer.Option("en", "--language"),
    limit: int = typer.Option(10, min=1, max=50),
):
    _print(asyncio.run(wikidata_search(query, language=language, limit=limit)))


@app.command("openalex")
def openalex_search_command(query: str, limit: int = typer.Option(25, min=1, max=100)):
    _print(asyncio.run(openalex_search(query, limit=limit)))


@app.command("crossref")
def crossref_search_command(query: str, limit: int = typer.Option(25, min=1, max=100)):
    _print(asyncio.run(crossref_search(query, limit=limit)))


@app.command("gitlab-user")
def gitlab_user_command(username: str):
    _print(asyncio.run(gitlab_user(username)))


@app.command("pypi")
def pypi_package_command(name: str):
    _print(asyncio.run(pypi_package(name)))


@app.command("npm")
def npm_package_command(name: str):
    _print(asyncio.run(npm_package(name)))


@app.command("crate")
def crates_package_command(name: str):
    _print(asyncio.run(crates_package(name)))


if __name__ == "__main__":
    app()
