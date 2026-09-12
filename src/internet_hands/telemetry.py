from __future__ import annotations

import dataclasses
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

DEFAULT_TELEMETRY_DB = Path(".internet-hands/telemetry.db")


@dataclasses.dataclass(frozen=True, slots=True)
class TelemetryEvent:
    id: int
    occurred_at: datetime
    event_type: str
    worker_id: str | None
    backend: str | None
    job_id: int | None
    url: str | None
    payload: dict[str, Any]


class TelemetrySink(Protocol):
    def emit(
        self,
        event_type: str,
        *,
        worker_id: str | None = None,
        backend: str | None = None,
        job_id: int | None = None,
        url: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> int | None: ...

    def list_events(self, *, after_id: int = 0, limit: int = 100) -> list[TelemetryEvent]: ...


class NullTelemetry:
    def emit(self, event_type: str, **kwargs) -> None:
        return None

    def list_events(self, *, after_id: int = 0, limit: int = 100) -> list[TelemetryEvent]:
        return []


class SqliteTelemetry:
    def __init__(self, path: Path = DEFAULT_TELEMETRY_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    worker_id TEXT,
                    backend TEXT,
                    job_id INTEGER,
                    url TEXT,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS telemetry_type_id_idx "
                "ON telemetry_events(event_type, id)"
            )

    def emit(
        self,
        event_type: str,
        *,
        worker_id: str | None = None,
        backend: str | None = None,
        job_id: int | None = None,
        url: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> int:
        if not event_type.strip():
            raise ValueError("event_type cannot be empty")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO telemetry_events (
                    occurred_at, event_type, worker_id, backend, job_id, url, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(UTC).isoformat(),
                    event_type,
                    worker_id,
                    backend,
                    job_id,
                    url,
                    json.dumps(payload or {}, sort_keys=True),
                ),
            )
            return int(cursor.lastrowid)

    def list_events(self, *, after_id: int = 0, limit: int = 100) -> list[TelemetryEvent]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM telemetry_events
                WHERE id > ?
                ORDER BY id
                LIMIT ?
                """,
                (after_id, limit),
            ).fetchall()
        return [self._from_sqlite(row) for row in rows]

    @staticmethod
    def _from_sqlite(row: sqlite3.Row) -> TelemetryEvent:
        return TelemetryEvent(
            id=int(row["id"]),
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            event_type=str(row["event_type"]),
            worker_id=row["worker_id"],
            backend=row["backend"],
            job_id=row["job_id"],
            url=row["url"],
            payload=json.loads(row["payload_json"] or "{}"),
        )


class PostgresTelemetry:
    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("Postgres DSN cannot be empty")
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install internet-hands[postgres] for Postgres telemetry") from exc
        self._psycopg = psycopg
        self.dsn = dsn
        self._init_schema()

    def _connect(self):
        return self._psycopg.connect(self.dsn)

    def _init_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_events (
                    id BIGSERIAL PRIMARY KEY,
                    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    event_type TEXT NOT NULL,
                    worker_id TEXT,
                    backend TEXT,
                    job_id BIGINT,
                    url TEXT,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS telemetry_type_id_idx "
                "ON telemetry_events(event_type, id)"
            )
            conn.commit()

    def emit(
        self,
        event_type: str,
        *,
        worker_id: str | None = None,
        backend: str | None = None,
        job_id: int | None = None,
        url: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> int:
        if not event_type.strip():
            raise ValueError("event_type cannot be empty")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO telemetry_events (
                    event_type, worker_id, backend, job_id, url, payload
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                RETURNING id
                """,
                (
                    event_type,
                    worker_id,
                    backend,
                    job_id,
                    url,
                    json.dumps(payload or {}, sort_keys=True),
                ),
            )
            event_id = int(cur.fetchone()[0])
            conn.commit()
        return event_id

    def list_events(self, *, after_id: int = 0, limit: int = 100) -> list[TelemetryEvent]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, occurred_at, event_type, worker_id, backend, job_id, url, payload
                FROM telemetry_events
                WHERE id > %s
                ORDER BY id
                LIMIT %s
                """,
                (after_id, limit),
            )
            rows = cur.fetchall()
        return [
            TelemetryEvent(
                id=int(row[0]),
                occurred_at=row[1],
                event_type=str(row[2]),
                worker_id=row[3],
                backend=row[4],
                job_id=row[5],
                url=row[6],
                payload=dict(row[7] or {}),
            )
            for row in rows
        ]
