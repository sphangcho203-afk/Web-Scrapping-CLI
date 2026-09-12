from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})\s+-->\s+"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})"
)
TOKEN_RE = re.compile(r"\b[\w'-]{2,}\b", flags=re.UNICODE)
URL_RE = re.compile(r"https?://[^\s<>]+")
HASHTAG_RE = re.compile(r"(?<!\w)#[\w-]+", flags=re.UNICODE)
MENTION_RE = re.compile(r"(?<!\w)@[\w.-]+", flags=re.UNICODE)
TAG_RE = re.compile(r"<[^>]+>")
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "he",
    "her",
    "his",
    "i",
    "if",
    "in",
    "is",
    "it",
    "its",
    "me",
    "my",
    "not",
    "of",
    "on",
    "or",
    "our",
    "she",
    "so",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "to",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
    "you",
    "your",
}


class MediaError(RuntimeError):
    pass


def _require_file(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise MediaError(f"Media/transcript file does not exist: {path}")
    return path


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    path = _require_file(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp_seconds(value: str) -> float:
    value = value.replace(",", ".")
    parts = value.split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(f"Unsupported timestamp: {value}")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def clean_transcript(text: str) -> tuple[str, list[dict[str, Any]]]:
    segments: list[dict[str, Any]] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    buffer: list[str] = []
    current_start: float | None = None
    current_end: float | None = None

    def flush() -> None:
        nonlocal buffer, current_start, current_end
        if not buffer:
            return
        joined = " ".join(part.strip() for part in buffer if part.strip())
        joined = TAG_RE.sub("", joined).strip()
        if joined:
            segments.append(
                {
                    "start_seconds": current_start,
                    "end_seconds": current_end,
                    "text": joined,
                }
            )
        buffer = []
        current_start = None
        current_end = None

    for raw in lines:
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.upper() == "WEBVTT" or line.startswith("NOTE"):
            continue
        if line.isdigit() and not buffer:
            continue
        match = TIMESTAMP_RE.search(line)
        if match:
            flush()
            current_start = _timestamp_seconds(match.group("start"))
            current_end = _timestamp_seconds(match.group("end"))
            continue
        buffer.append(line)
    flush()

    if not segments:
        plain = TAG_RE.sub("", text)
        plain = " ".join(plain.split())
        if plain:
            segments.append(
                {"start_seconds": None, "end_seconds": None, "text": plain}
            )

    cleaned = "\n".join(segment["text"] for segment in segments)
    return cleaned, segments


def analyze_transcript(text: str) -> dict[str, Any]:
    cleaned, segments = clean_transcript(text)
    tokens = [token.lower() for token in TOKEN_RE.findall(cleaned)]
    content_tokens = [
        token
        for token in tokens
        if token not in STOP_WORDS and not token.startswith(("http", "www"))
    ]
    counts = Counter(content_tokens)
    timestamps = [
        segment["end_seconds"]
        for segment in segments
        if segment["end_seconds"] is not None
    ]
    duration = max(timestamps) if timestamps else None
    words_per_minute = None
    if duration and duration > 0:
        words_per_minute = round(len(tokens) / (duration / 60), 2)

    return {
        "text": cleaned,
        "segments": segments,
        "metrics": {
            "characters": len(cleaned),
            "words": len(tokens),
            "unique_words": len(set(tokens)),
            "segments": len(segments),
            "duration_seconds": duration,
            "words_per_minute": words_per_minute,
        },
        "signals": {
            "top_terms": [
                {"term": term, "count": count}
                for term, count in counts.most_common(30)
            ],
            "hashtags": sorted(set(HASHTAG_RE.findall(cleaned))),
            "mentions": sorted(set(MENTION_RE.findall(cleaned))),
            "urls": sorted(set(URL_RE.findall(cleaned))),
        },
    }


def analyze_transcript_file(path: Path) -> dict[str, Any]:
    path = _require_file(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    result = analyze_transcript(text)
    result["source"] = {
        "path": str(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }
    return result


def probe_media(path: Path, *, timeout: int = 30) -> dict[str, Any]:
    path = _require_file(path)
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise MediaError("ffprobe is required for media probing and was not found on PATH")
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        error = completed.stderr.strip()[:1000]
        raise MediaError(f"ffprobe failed: {error}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MediaError("ffprobe returned invalid JSON") from exc
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "probe": payload,
    }


def sample_frames(
    path: Path,
    output_dir: Path,
    *,
    every_seconds: float = 30.0,
    max_frames: int = 20,
    timeout: int = 180,
) -> dict[str, Any]:
    path = _require_file(path)
    if every_seconds <= 0:
        raise ValueError("every_seconds must be > 0")
    if max_frames < 1 or max_frames > 200:
        raise ValueError("max_frames must be between 1 and 200")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise MediaError("ffmpeg is required for frame sampling and was not found on PATH")

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = output_dir / "frame-%04d.jpg"
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-vf",
        f"fps=1/{every_seconds:g}",
        "-frames:v",
        str(max_frames),
        "-q:v",
        "2",
        "-y",
        str(pattern),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        error = completed.stderr.strip()[:1000]
        raise MediaError(f"ffmpeg failed: {error}")

    frames = sorted(output_dir.glob("frame-*.jpg"))
    return {
        "source": {"path": str(path), "sha256": sha256_file(path)},
        "sampling": {
            "every_seconds": every_seconds,
            "max_frames": max_frames,
            "frames_created": len(frames),
        },
        "frames": [
            {
                "path": str(frame),
                "sha256": sha256_file(frame),
                "bytes": frame.stat().st_size,
            }
            for frame in frames
        ],
    }


def build_media_bundle(
    path: Path,
    *,
    output_root: Path = Path(".internet-hands/media"),
    transcript: Path | None = None,
    every_seconds: float = 30.0,
    max_frames: int = 20,
) -> dict[str, Any]:
    path = _require_file(path)
    digest = sha256_file(path)
    root = (output_root / digest[:16]).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "media": probe_media(path),
        "frames": sample_frames(
            path,
            root / "frames",
            every_seconds=every_seconds,
            max_frames=max_frames,
        ),
        "transcript": None,
        "bundle_dir": str(root),
    }
    if transcript:
        result["transcript"] = analyze_transcript_file(transcript)

    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    result["manifest"] = str(manifest)
    return result
