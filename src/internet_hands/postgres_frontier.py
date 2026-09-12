from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from .frontier import FrontierJob, JobState
from .hunt import canonicalize_url
from .policy import validate_public_http_url

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS frontier_jobs (
    id BIGSERIAL PRIMARY KEY,
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
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
    opened_until TIMESTAMPTZ,
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS host_rate_limits (
    host TEXT PRIMARY KEY,
    next_allowed_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


class PostgresFrontier:
    """Postgres frontier using row locks and SKIP LOCKED for distributed workers."""

    def __init__(self, dsn: str, *, initialize: bool = True) -> None:
        if not dsn.strip():
            raise ValueError("Postgres DSN cannot be empty")
        self.dsn = dsn
        if initialize:
            self.init_schema()

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "Postgres support is optional. Install with: pip install 'internet-hands[postgres]'"
            ) from exc
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(POSTGRES_SCHEMA)

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
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO frontier_jobs (
                    url, canonical_url, host, root_url, scope, depth,
                    parent, priority, max_attempts
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(canonical_url) DO NOTHING
                RETURNING id
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
                ),
            ).fetchone()
        return row is not None

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

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE frontier_jobs SET
                    state = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'queued' END,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    available_at = NOW(),
                    last_error = COALESCE(last_error, 'worker lease expired'),
                    updated_at = NOW()
                WHERE state = 'leased' AND lease_expires_at <= NOW()
                """
            )
            rows = conn.execute(
                """
                WITH picked AS (
                    SELECT id
                    FROM frontier_jobs
                    WHERE state = 'queued' AND available_at <= NOW()
                    ORDER BY priority DESC, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                UPDATE frontier_jobs AS jobs SET
                    state = 'leased',
                    lease_owner = %s,
                    lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                    attempts = jobs.attempts + 1,
                    updated_at = NOW()
                FROM picked
                WHERE jobs.id = picked.id
                RETURNING jobs.*
                """,
                (limit, worker_id, lease_seconds),
            ).fetchall()
        return [self._job(row) for row in rows]

    def ack(self, job_id: int, worker_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE frontier_jobs SET
                    state = 'done', lease_owner = NULL, lease_expires_at = NULL,
                    last_error = NULL, updated_at = NOW()
                WHERE id = %s AND state = 'leased' AND lease_owner = %s
                RETURNING id
                """,
                (job_id, worker_id),
            ).fetchone()
        return row is not None

    def fail(
        self,
        job_id: int,
        worker_id: str,
        error: str,
        *,
        base_backoff_seconds: float = 2.0,
        max_backoff_seconds: float = 300.0,
    ) -> JobState | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT attempts, max_attempts
                FROM frontier_jobs
                WHERE id = %s AND state = 'leased' AND lease_owner = %s
                FOR UPDATE
                """,
                (job_id, worker_id),
            ).fetchone()
            if row is None:
                return None
            attempts = int(row["attempts"])
            max_attempts = int(row["max_attempts"])
            if attempts >= max_attempts:
                state = JobState.DEAD
                delay = 0.0
            else:
                state = JobState.QUEUED
                jitter = random.uniform(0.85, 1.15)
                delay = min(max_backoff_seconds, base_backoff_seconds * (2 ** (attempts - 1)))
                delay *= jitter
            conn.execute(
                """
                UPDATE frontier_jobs SET
                    state = %s,
                    available_at = NOW() + (%s * INTERVAL '1 second'),
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    last_error = %s,
                    updated_at = NOW()
                WHERE id = %s AND lease_owner = %s
                """,
                (state.value, delay, error[:4000], job_id, worker_id),
            )
        return state

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT state, COUNT(*) AS count FROM frontier_jobs GROUP BY state"
            ).fetchall()
        output = {state.value: 0 for state in JobState}
        output.update({str(row["state"]): int(row["count"]) for row in rows})
        return output

    def circuit_allows(self, key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT opened_until FROM circuit_state WHERE key = %s",
                (key,),
            ).fetchone()
        return row is None or row["opened_until"] is None or row["opened_until"] <= datetime.now(UTC)

    def circuit_success(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO circuit_state (key, consecutive_failures, opened_until, last_error)
                VALUES (%s, 0, NULL, NULL)
                ON CONFLICT(key) DO UPDATE SET
                    consecutive_failures = 0,
                    opened_until = NULL,
                    last_error = NULL,
                    updated_at = NOW()
                """,
                (key,),
            )

    def circuit_failure(
        self,
        key: str,
        error: str,
        *,
        threshold: int = 5,
        cooldown_seconds: int = 60,
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT consecutive_failures FROM circuit_state WHERE key = %s FOR UPDATE",
                (key,),
            ).fetchone()
            failures = (int(row["consecutive_failures"]) if row else 0) + 1
            opened = failures >= threshold
            opened_until = (
                datetime.now(UTC) + timedelta(seconds=cooldown_seconds)
                if opened
                else None
            )
            conn.execute(
                """
                INSERT INTO circuit_state (
                    key, consecutive_failures, opened_until, last_error
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT(key) DO UPDATE SET
                    consecutive_failures = EXCLUDED.consecutive_failures,
                    opened_until = EXCLUDED.opened_until,
                    last_error = EXCLUDED.last_error,
                    updated_at = NOW()
                """,
                (key, failures, opened_until, error[:4000]),
            )
        return opened

    def reserve_host_slot(self, host: str, *, min_delay_seconds: float) -> float:
        now = datetime.now(UTC)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT next_allowed_at FROM host_rate_limits WHERE host = %s FOR UPDATE",
                (host,),
            ).fetchone()
            slot = max(now, row["next_allowed_at"]) if row else now
            next_allowed = slot + timedelta(seconds=min_delay_seconds)
            conn.execute(
                """
                INSERT INTO host_rate_limits (host, next_allowed_at)
                VALUES (%s, %s)
                ON CONFLICT(host) DO UPDATE SET
                    next_allowed_at = EXCLUDED.next_allowed_at,
                    updated_at = NOW()
                """,
                (host, next_allowed),
            )
        return max(0.0, (slot - now).total_seconds())

    @staticmethod
    def _job(row: dict[str, Any]) -> FrontierJob:
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
            available_at=row["available_at"],
            lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
            last_error=row["last_error"],
        )
