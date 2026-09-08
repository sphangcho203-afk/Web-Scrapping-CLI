from __future__ import annotations

import base64
import json
import re
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import ExtractedDocument, FetchResult, SearchHit, WatchJob, WatchRun

DEFAULT_DB = Path(".internet-hands/internet-hands.db")
DEFAULT_OBJECTS = Path(".internet-hands/objects")


class Store:
    def __init__(self, path: Path = DEFAULT_DB, objects: Path = DEFAULT_OBJECTS) -> None:
        self.path = Path(path)
        self.objects = Path(objects)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.objects.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS captures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_url TEXT NOT NULL,
                    final_url TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    content_type TEXT,
                    content_length INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    elapsed_ms REAL NOT NULL,
                    captured_at TEXT NOT NULL,
                    headers_json TEXT NOT NULL,
                    content_path TEXT
                );
                CREATE INDEX IF NOT EXISTS captures_url_idx ON captures(final_url);
                CREATE INDEX IF NOT EXISTS captures_sha_idx ON captures(sha256);

                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capture_id INTEGER NOT NULL UNIQUE REFERENCES captures(id) ON DELETE CASCADE,
                    url TEXT NOT NULL,
                    title TEXT,
                    description TEXT,
                    text TEXT NOT NULL,
                    headings_json TEXT NOT NULL,
                    links_json TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS documents_url_idx ON documents(url);

                CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                    title, description, text, content='documents', content_rowid='id'
                );

                CREATE TABLE IF NOT EXISTS watches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    interval_seconds INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_checked_at TEXT,
                    last_sha256 TEXT,
                    next_run_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS watch_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
                    checked_at TEXT NOT NULL,
                    changed INTEGER NOT NULL,
                    status_code INTEGER,
                    sha256 TEXT,
                    error TEXT
                );
                """
            )

    def save_fetch(self, result: FetchResult, document: ExtractedDocument | None = None) -> int:
        content_path = self._persist_body(result)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO captures (
                    request_url, final_url, status_code, content_type, content_length,
                    sha256, elapsed_ms, captured_at, headers_json, content_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.request_url,
                    result.final_url,
                    result.status_code,
                    result.content_type,
                    result.content_length,
                    result.sha256,
                    result.elapsed_ms,
                    result.captured_at.isoformat(),
                    json.dumps(result.headers, sort_keys=True),
                    str(content_path) if content_path else None,
                ),
            )
            capture_id = int(cur.lastrowid)
            if document is not None:
                doc_cur = conn.execute(
                    """
                    INSERT INTO documents (
                        capture_id, url, title, description, text, headings_json,
                        links_json, sha256, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        capture_id,
                        document.url,
                        document.title,
                        document.description,
                        document.text,
                        json.dumps(document.headings),
                        json.dumps(document.links),
                        document.sha256,
                        document.captured_at.isoformat(),
                    ),
                )
                doc_id = int(doc_cur.lastrowid)
                conn.execute(
                    "INSERT INTO documents_fts(rowid, title, description, text) "
                    "VALUES (?, ?, ?, ?)",
                    (doc_id, document.title or "", document.description or "", document.text),
                )
            return capture_id

    def search(self, query: str, limit: int = 20) -> list[SearchHit]:
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        tokens = re.findall(r"[\w-]+", query, flags=re.UNICODE)
        if not tokens:
            return []
        expression = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT d.id, d.url, d.title, d.description, d.created_at, d.sha256,
                       snippet(documents_fts, 2, '[', ']', ' … ', 24) AS snippet,
                       bm25(documents_fts) AS score
                FROM documents_fts
                JOIN documents d ON d.id = documents_fts.rowid
                WHERE documents_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (expression, limit),
            ).fetchall()
        return [
            SearchHit(
                document_id=row["id"],
                url=row["url"],
                title=row["title"],
                description=row["description"],
                snippet=row["snippet"] or "",
                score=float(row["score"]),
                captured_at=datetime.fromisoformat(row["created_at"]),
                sha256=row["sha256"],
            )
            for row in rows
        ]

    def export_jsonl(self, target: Path) -> int:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with self._connect() as conn, target.open("w", encoding="utf-8") as handle:
            rows = conn.execute(
                """
                SELECT d.*, c.status_code, c.content_type, c.content_length,
                       c.headers_json, c.content_path, c.request_url
                FROM documents d
                JOIN captures c ON c.id = d.capture_id
                ORDER BY d.id
                """
            )
            for row in rows:
                record = dict(row)
                record["headings"] = json.loads(record.pop("headings_json"))
                record["links"] = json.loads(record.pop("links_json"))
                record["headers"] = json.loads(record.pop("headers_json"))
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
        return count

    def add_watch(self, url: str, interval_seconds: int) -> WatchJob:
        if interval_seconds < 60:
            raise ValueError("interval_seconds must be at least 60")
        now = datetime.now(UTC)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO watches (
                    url, interval_seconds, enabled, next_run_at, created_at, updated_at
                ) VALUES (?, ?, 1, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    interval_seconds=excluded.interval_seconds,
                    enabled=1,
                    next_run_at=excluded.next_run_at,
                    updated_at=excluded.updated_at
                """,
                (url, interval_seconds, now.isoformat(), now.isoformat(), now.isoformat()),
            )
            row = conn.execute("SELECT * FROM watches WHERE url = ?", (url,)).fetchone()
        return self._watch_from_row(row)

    def list_watches(self, enabled_only: bool = False) -> list[WatchJob]:
        sql = "SELECT * FROM watches"
        params: tuple[object, ...] = ()
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY id"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._watch_from_row(row) for row in rows]

    def due_watches(self, now: datetime | None = None, limit: int = 100) -> list[WatchJob]:
        now = now or datetime.now(UTC)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM watches
                WHERE enabled = 1 AND next_run_at <= ?
                ORDER BY next_run_at
                LIMIT ?
                """,
                (now.isoformat(), limit),
            ).fetchall()
        return [self._watch_from_row(row) for row in rows]

    def record_watch_run(self, job: WatchJob, run: WatchRun) -> None:
        next_run = run.checked_at + timedelta(seconds=job.interval_seconds)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO watch_events (
                    watch_id, checked_at, changed, status_code, sha256, error
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    run.checked_at.isoformat(),
                    int(run.changed),
                    run.status_code,
                    run.sha256,
                    run.error,
                ),
            )
            conn.execute(
                """
                UPDATE watches SET
                    last_checked_at = ?, last_sha256 = COALESCE(?, last_sha256),
                    next_run_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    run.checked_at.isoformat(),
                    run.sha256,
                    next_run.isoformat(),
                    run.checked_at.isoformat(),
                    job.id,
                ),
            )

    def _persist_body(self, result: FetchResult) -> Path | None:
        if result.body_text is None and result.body_base64 is None:
            return None
        target = self.objects / result.sha256[:2] / result.sha256
        if target.exists():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        if result.body_base64 is not None:
            payload = base64.b64decode(result.body_base64)
        else:
            payload = (result.body_text or "").encode("utf-8")
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(payload)
        temporary.replace(target)
        return target

    @staticmethod
    def _watch_from_row(row: sqlite3.Row) -> WatchJob:
        return WatchJob(
            id=row["id"],
            url=row["url"],
            interval_seconds=row["interval_seconds"],
            enabled=bool(row["enabled"]),
            last_checked_at=(
                datetime.fromisoformat(row["last_checked_at"])
                if row["last_checked_at"]
                else None
            ),
            last_sha256=row["last_sha256"],
            next_run_at=datetime.fromisoformat(row["next_run_at"]),
        )


def iter_jsonl(path: Path) -> Iterable[dict[str, object]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)
