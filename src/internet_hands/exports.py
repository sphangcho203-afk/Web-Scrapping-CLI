from __future__ import annotations

import contextlib
import gzip
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import BinaryIO

from .storage import DEFAULT_DB


def export_warc(db_path: Path, target: Path) -> int:
    """Export stored captures as WARC/1.1 response records."""
    db_path = Path(db_path)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with sqlite3.connect(db_path) as conn, _binary_writer(target) as handle:
        conn.row_factory = sqlite3.Row
        _write_warcinfo(handle)
        rows = conn.execute("SELECT * FROM captures ORDER BY id")
        for row in rows:
            body = _read_capture_body(row["content_path"])
            headers = json.loads(row["headers_json"] or "{}")
            http_message = _http_response_message(
                int(row["status_code"]),
                headers,
                body,
            )
            captured_at = datetime.fromisoformat(row["captured_at"])
            _write_warc_record(
                handle,
                target_uri=str(row["final_url"]),
                captured_at=captured_at,
                sha256=str(row["sha256"]),
                payload=http_message,
            )
            count += 1
    return count


def export_parquet(db_path: Path, target: Path) -> int:
    """Export normalized documents/capture metadata as a Parquet table."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "Parquet support is optional. Install with: pip install 'internet-hands[parquet]'"
        ) from exc

    db_path = Path(db_path)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                d.id AS document_id,
                d.capture_id,
                d.url,
                d.title,
                d.description,
                d.text,
                d.headings_json,
                d.links_json,
                d.sha256,
                d.created_at,
                c.request_url,
                c.final_url,
                c.status_code,
                c.content_type,
                c.content_length,
                c.elapsed_ms,
                c.headers_json,
                c.content_path
            FROM documents d
            JOIN captures c ON c.id = d.capture_id
            ORDER BY d.id
            """
        )
        for row in rows:
            records.append(
                {
                    "document_id": int(row["document_id"]),
                    "capture_id": int(row["capture_id"]),
                    "url": row["url"],
                    "title": row["title"],
                    "description": row["description"],
                    "text": row["text"],
                    "headings": row["headings_json"],
                    "links": row["links_json"],
                    "sha256": row["sha256"],
                    "created_at": row["created_at"],
                    "request_url": row["request_url"],
                    "final_url": row["final_url"],
                    "status_code": int(row["status_code"]),
                    "content_type": row["content_type"],
                    "content_length": int(row["content_length"]),
                    "elapsed_ms": float(row["elapsed_ms"]),
                    "headers": row["headers_json"],
                    "content_path": row["content_path"],
                }
            )
    table = pa.Table.from_pylist(records)
    pq.write_table(table, target, compression="zstd")
    return len(records)


def _binary_writer(target: Path):
    if target.name.endswith(".gz"):
        return gzip.open(target, "wb")
    return target.open("wb")


def _write_warcinfo(handle: BinaryIO) -> None:
    body = (
        b"software: Internet Hands 0.3\r\n"
        b"format: WARC File Format 1.1\r\n"
        b"conformsTo: https://iipc.github.io/warc-specifications/specifications/warc-format/warc-1.1/\r\n"
    )
    header = _warc_header(
        warc_type="warcinfo",
        record_id=f"<urn:uuid:{uuid.uuid4()}>",
        captured_at=datetime.now(UTC),
        content_type="application/warc-fields",
        content_length=len(body),
    )
    handle.write(header + body + b"\r\n\r\n")


def _write_warc_record(
    handle: BinaryIO,
    *,
    target_uri: str,
    captured_at: datetime,
    sha256: str,
    payload: bytes,
) -> None:
    header = _warc_header(
        warc_type="response",
        record_id=f"<urn:uuid:{uuid.uuid4()}>",
        captured_at=captured_at,
        target_uri=target_uri,
        payload_digest=f"sha256:{sha256}",
        content_type="application/http; msgtype=response",
        content_length=len(payload),
    )
    handle.write(header + payload + b"\r\n\r\n")


def _warc_header(
    *,
    warc_type: str,
    record_id: str,
    captured_at: datetime,
    content_type: str,
    content_length: int,
    target_uri: str | None = None,
    payload_digest: str | None = None,
) -> bytes:
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=UTC)
    date = captured_at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    lines = [
        "WARC/1.1",
        f"WARC-Type: {warc_type}",
        f"WARC-Record-ID: {record_id}",
        f"WARC-Date: {date}",
    ]
    if target_uri is not None:
        lines.append(f"WARC-Target-URI: {target_uri}")
    if payload_digest is not None:
        lines.append(f"WARC-Payload-Digest: {payload_digest}")
    lines.extend(
        [
            f"Content-Type: {content_type}",
            f"Content-Length: {content_length}",
            "",
            "",
        ]
    )
    return "\r\n".join(lines).encode("utf-8")


def _http_response_message(status_code: int, headers: dict[str, str], body: bytes) -> bytes:
    with contextlib.suppress(ValueError):
        phrase = HTTPStatus(status_code).phrase
        status_line = f"HTTP/1.1 {status_code} {phrase}\r\n"
        return _render_http(status_line, headers, body)
    return _render_http(f"HTTP/1.1 {status_code}\r\n", headers, body)


def _render_http(status_line: str, headers: dict[str, str], body: bytes) -> bytes:
    rendered_headers = "".join(f"{key}: {value}\r\n" for key, value in headers.items())
    return (status_line + rendered_headers + "\r\n").encode("utf-8") + body


def _read_capture_body(content_path: str | None) -> bytes:
    if not content_path:
        return b""
    path = Path(content_path)
    if not path.exists():
        return b""
    return path.read_bytes()
