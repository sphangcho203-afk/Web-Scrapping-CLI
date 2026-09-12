from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from .media import (
    analyze_transcript_file,
    build_media_bundle,
    probe_media,
    sample_frames,
)

app = typer.Typer(no_args_is_help=True, help="Analyze authorized or caller-supplied media evidence.")
console = Console()


def _print(value) -> None:
    console.print_json(json.dumps(value, default=str))


@app.command()
def probe(path: Path):
    """Read technical media metadata with ffprobe and hash the source file."""
    _print(probe_media(path))


@app.command()
def transcript(path: Path):
    """Analyze a caller-supplied plain text, SRT, or WebVTT transcript."""
    _print(analyze_transcript_file(path))


@app.command()
def frames(
    path: Path,
    output_dir: Path,
    every_seconds: float = 30.0,
    max_frames: int = 20,
):
    """Sample deterministic evidence frames from a local media file."""
    _print(
        sample_frames(
            path,
            output_dir,
            every_seconds=every_seconds,
            max_frames=max_frames,
        )
    )


@app.command()
def bundle(
    path: Path,
    transcript_path: Path | None = None,
    output_root: Path = Path(".internet-hands/media"),
    every_seconds: float = 30.0,
    max_frames: int = 20,
):
    """Create a hashed media evidence bundle with probe, frames, and optional transcript."""
    _print(
        build_media_bundle(
            path,
            output_root=output_root,
            transcript=transcript_path,
            every_seconds=every_seconds,
            max_frames=max_frames,
        )
    )


if __name__ == "__main__":
    app()
