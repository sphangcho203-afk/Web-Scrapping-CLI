from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .frontier import DEFAULT_FRONTIER_DB


class DistributedHostLimiter:
    """Reserve per-host request slots across multiple local worker processes."""

    def __init__(self, path: Path = DEFAULT_FRONTIER_DB) -> None:
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
                CREATE TABLE IF NOT EXISTS host_rate_limits (
                    host TEXT PRIMARY KEY,
                    next_allowed_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def reserve(self, host: str, *, min_delay_seconds: float) -> float:
        host = host.strip().lower()
        if not host:
            raise ValueError("host cannot be empty")
        if not 0.0 <= min_delay_seconds <= 3600.0:
            raise ValueError("min_delay_seconds must be between 0 and 3600")

        now = datetime.now(UTC)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT next_allowed_at FROM host_rate_limits WHERE host = ?",
                (host,),
            ).fetchone()
            previous = datetime.fromisoformat(row["next_allowed_at"]) if row else now
            slot = max(now, previous)
            next_allowed = slot + timedelta(seconds=min_delay_seconds)
            conn.execute(
                """
                INSERT INTO host_rate_limits (host, next_allowed_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(host) DO UPDATE SET
                    next_allowed_at = excluded.next_allowed_at,
                    updated_at = excluded.updated_at
                """,
                (host, next_allowed.isoformat(), now.isoformat()),
            )
        return max(0.0, (slot - now).total_seconds())
