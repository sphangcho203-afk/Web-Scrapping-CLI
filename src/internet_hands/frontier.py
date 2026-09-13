from __future__ import annotations

import dataclasses
import random
import sqlite3
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

from .hunt import canonicalize_url
from .policy import validate_public_http_url

DEFAULT_FRONTIER_DB = Path(".internet-hands/frontier.db")


class JobState(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    DONE = "done"
    DEAD = "dead"


@dataclasses.dataclass(frozen=True, slots=True)
class FrontierJob:
    id: int
    url: str
    root_url: str
    scope: str
    depth: int
    parent: str | None
    priority: int
    state: JobState
    attempts: int
    max_attempts: int
    available_at: datetime
    lease_owner: str | None
    lease_expires_at: datetime | None
    last_error: str | None


class FrontierStore:
    """Durable SQLite crawl queue with leases, retries, and circuit state."""

    def __init__(self, path: Path = DEFAULT_FRONTIER_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS frontier_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    canonical_url TEXT NOT NULL UNIQUE,
                    host TEXT NOT NULL,
                    root_url TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    parent TEXT,
                    priority INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL DEFAULT 'queued',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 4,
                    available_at TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS frontier_ready_idx
                    ON frontier_jobs(state, available_at, priority DESC, id);
                CREATE INDEX IF NOT EXISTS frontier_lease_idx
                    ON frontier_jobs(state, lease_expires_at);
                CREATE INDEX IF NOT EXISTS frontier_host_idx
                    ON frontier_jobs(host, state);

                CREATE TABLE IF NOT EXISTS circuit_state (
                    key TEXT PRIMARY KEY,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    opened_until TEXT,
                    last_error TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def enqueue(
        self,
        url: str,
        *,
        root_url: str | None = None,
        scope: str = "origin",
        depth: int = 0,
        parent: str | None = None,
        priority: int = 0,
        max_attempts: int = 4,
    ) -> bool:
        canonical = canonicalize_url(url)
        validate_public_http_url(canonical)
        root = canonicalize_url(root_url or canonical)
        validate_public_http_url(root)
        host = (urlsplit(canonical).hostname or "").lower()
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO frontier_jobs (
                    url, canonical_url, host, root_url, scope, depth, parent,
                    priority, max_attempts, available_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    url,
                    canonical,
                    host,
                    root,
                    scope,
                    depth,
                    parent,
                    priority,
                    max_attempts,
                    now,
                    now,
                    now,
                ),
            )
            return cursor.rowcount == 1

    def enqueue_many(self, urls: list[str], **kwargs) -> int:
        added = 0
        for url in urls:
            try:
                added += int(self.enqueue(url, **kwargs))
            except (ValueError, OSError):
                continue
        return added

    def lease(
        self,
        worker_id: str,
        *,
        limit: int = 8,
        lease_seconds: int = 90,
    ) -> list[FrontierJob]:
        if not worker_id.strip():
            raise ValueError("worker_id cannot be empty")
        if not 1 <= limit <= 256:
            raise ValueError("limit must be between 1 and 256")
        if not 10 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 10 and 3600")

        now = datetime.now(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._requeue_expired_conn(conn, now)
            rows = conn.execute(
                """
                SELECT id FROM frontier_jobs
                WHERE state = 'queued' AND available_at <= ?
                ORDER BY priority DESC, id
                LIMIT ?
                """,
                (now.isoformat(), limit),
            ).fetchall()
            ids = [int(row["id"]) for row in rows]
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"""
                UPDATE frontier_jobs SET
                    state = 'leased',
                    lease_owner = ?,
                    lease_expires_at = ?,
                    attempts = attempts + 1,
                    updated_at = ?
                WHERE id IN ({placeholders})
                """,
                (worker_id, expires.isoformat(), now.isoformat(), *ids),
            )
            leased = conn.execute(
                f"SELECT * FROM frontier_jobs WHERE id IN ({placeholders}) ORDER BY priority DESC, id",
                ids,
            ).fetchall()
        return [self._job_from_row(row) for row in leased]

    def ack(self, job_id: int, worker_id: str) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE frontier_jobs SET
                    state = 'done', lease_owner = NULL, lease_expires_at = NULL,
                    last_error = NULL, updated_at = ?
                WHERE id = ? AND state = 'leased' AND lease_owner = ?
                """,
                (now, job_id, worker_id),
            )
            return cursor.rowcount == 1

    def fail(
        self,
        job_id: int,
        worker_id: str,
        error: str,
        *,
        base_backoff_seconds: float = 2.0,
        max_backoff_seconds: float = 300.0,
    ) -> JobState | None:
        now = datetime.now(UTC)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT attempts, max_attempts FROM frontier_jobs
                WHERE id = ? AND state = 'leased' AND lease_owner = ?
                """,
                (job_id, worker_id),
            ).fetchone()
            if row is None:
                return None
            attempts = int(row["attempts"])
            max_attempts = int(row["max_attempts"])
            if attempts >= max_attempts:
                state = JobState.DEAD
                available_at = now
            else:
                state = JobState.QUEUED
                jitter = random.uniform(0.85, 1.15)
                delay = min(max_backoff_seconds, base_backoff_seconds * (2 ** (attempts - 1)))
                available_at = now + timedelta(seconds=delay * jitter)
            conn.execute(
                """
                UPDATE frontier_jobs SET
                    state = ?, available_at = ?, lease_owner = NULL,
                    lease_expires_at = NULL, last_error = ?, updated_at = ?
                WHERE id = ? AND lease_owner = ?
                """,
                (
                    state.value,
                    available_at.isoformat(),
                    error[:4000],
                    now.isoformat(),
                    job_id,
                    worker_id,
                ),
            )
            return state

    def requeue_expired(self) -> int:
        now = datetime.now(UTC)
        with self._connect() as conn:
            return self._requeue_expired_conn(conn, now)

    def _requeue_expired_conn(self, conn: sqlite3.Connection, now: datetime) -> int:
        cursor = conn.execute(
            """
            UPDATE frontier_jobs SET
                state = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'queued' END,
                lease_owner = NULL,
                lease_expires_at = NULL,
                available_at = ?,
                last_error = COALESCE(last_error, 'worker lease expired'),
                updated_at = ?
            WHERE state = 'leased' AND lease_expires_at <= ?
            """,
            (now.isoformat(), now.isoformat(), now.isoformat()),
        )
        return cursor.rowcount

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT state, COUNT(*) AS count FROM frontier_jobs GROUP BY state"
            ).fetchall()
        output = {state.value: 0 for state in JobState}
        output.update({str(row["state"]): int(row["count"]) for row in rows})
        return output

    def circuit_allows(self, key: str) -> bool:
        now = datetime.now(UTC)
        with self._connect() as conn:
            row = conn.execute("SELECT opened_until FROM circuit_state WHERE key = ?", (key,)).fetchone()
        if row is None or row["opened_until"] is None:
            return True
        return datetime.fromisoformat(row["opened_until"]) <= now

    def circuit_success(self, key: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO circuit_state (key, consecutive_failures, opened_until, last_error, updated_at)
                VALUES (?, 0, NULL, NULL, ?)
                ON CONFLICT(key) DO UPDATE SET
                    consecutive_failures = 0, opened_until = NULL,
                    last_error = NULL, updated_at = excluded.updated_at
                """,
                (key, now),
            )

    def circuit_failure(
        self,
        key: str,
        error: str,
        *,
        threshold: int = 5,
        cooldown_seconds: int = 60,
    ) -> bool:
        if threshold < 1:
            raise ValueError("threshold must be positive")
        now = datetime.now(UTC)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT consecutive_failures FROM circuit_state WHERE key = ?",
                (key,),
            ).fetchone()
            failures = (int(row["consecutive_failures"]) if row else 0) + 1
            opened_until = (
                now + timedelta(seconds=cooldown_seconds)
                if failures >= threshold
                else None
            )
            conn.execute(
                """
                INSERT INTO circuit_state (
                    key, consecutive_failures, opened_until, last_error, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    consecutive_failures = excluded.consecutive_failures,
                    opened_until = excluded.opened_until,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (
                    key,
                    failures,
                    opened_until.isoformat() if opened_until else None,
                    error[:4000],
                    now.isoformat(),
                ),
            )
        return opened_until is not None

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> FrontierJob:
        return FrontierJob(
            id=int(row["id"]),
            url=str(row["canonical_url"]),
            root_url=str(row["root_url"]),
            scope=str(row["scope"]),
            depth=int(row["depth"]),
            parent=row["parent"],
            priority=int(row["priority"]),
            state=JobState(row["state"]),
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            available_at=datetime.fromisoformat(row["available_at"]),
            lease_owner=row["lease_owner"],
            lease_expires_at=(
                datetime.fromisoformat(row["lease_expires_at"])
                if row["lease_expires_at"]
                else None
            ),
            last_error=row["last_error"],
        )
