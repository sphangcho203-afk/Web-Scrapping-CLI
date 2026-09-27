from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

_SHARED_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ih_provider_reliability (
    provider text PRIMARY KEY,
    successes bigint NOT NULL DEFAULT 0,
    failures bigint NOT NULL DEFAULT 0,
    neutral bigint NOT NULL DEFAULT 0,
    consecutive_failures integer NOT NULL DEFAULT 0,
    ewma_latency_ms double precision,
    last_success_at timestamptz,
    last_failure_at timestamptz,
    last_error text,
    last_error_class text,
    circuit_open_until timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_provider_reliability_updated_idx
    ON ih_provider_reliability(updated_at DESC);
"""

_SUCCESS_STATUSES = {
    "completed",
    "complete",
    "ok",
    "success",
    "succeeded",
    "running",
    "queued",
    "pending",
    "accepted",
}
_NEUTRAL_STATUSES = {"blocked", "dry_run", "cancelled", "canceled"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _shared_enabled() -> bool:
    return os.getenv(
        "OPENCRAWL_PROVIDER_SHARED_RELIABILITY",
        "true",
    ).strip().lower() not in {"0", "false", "no", "off"}


def _selected_dsn() -> str | None:
    control_dsn = os.getenv("INTERNET_HANDS_CONTROL_POSTGRES_DSN")
    neon_dsn = os.getenv("INTERNET_HANDS_POSTGRES_DSN")
    primary = (os.getenv("OPENCRAWL_PRIMARY_DATABASE") or "supabase").strip().lower()
    if primary == "neon" and neon_dsn:
        return neon_dsn
    return control_dsn or neon_dsn


def _kind(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in _NEUTRAL_STATUSES:
        return "neutral"
    if normalized in _SUCCESS_STATUSES:
        return "success"
    return "failure"


def ensure_provider_reliability_schema(cur: Any) -> None:
    cur.execute(_SHARED_SCHEMA_SQL)


def record_provider_reliability_event(
    cur: Any,
    event: dict[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    provider = str(event.get("provider") or "").strip().lower()[:80]
    if not provider:
        return
    current = now or datetime.now(UTC)
    status = str(event.get("status") or "unknown")
    kind = _kind(status)
    latency_raw = event.get("duration_ms")
    latency = (
        max(0, int(latency_raw))
        if isinstance(latency_raw, (int, float)) and not isinstance(latency_raw, bool)
        else None
    )
    error = str(event.get("error") or "").strip()[:500] or None
    error_class = str(event.get("error_class") or "").strip().lower()[:80] or None

    cur.execute(
        """
        SELECT provider,successes,failures,neutral,consecutive_failures,
               ewma_latency_ms,last_success_at,last_failure_at,last_error,
               last_error_class,circuit_open_until
        FROM ih_provider_reliability
        WHERE provider=%s
        FOR UPDATE
        """,
        (provider,),
    )
    row = cur.fetchone()

    successes = int((row or {}).get("successes") or 0)
    failures = int((row or {}).get("failures") or 0)
    neutral = int((row or {}).get("neutral") or 0)
    streak = int((row or {}).get("consecutive_failures") or 0)
    ewma = (row or {}).get("ewma_latency_ms")
    last_success = (row or {}).get("last_success_at")
    last_failure = (row or {}).get("last_failure_at")
    last_error = (row or {}).get("last_error")
    last_error_class = (row or {}).get("last_error_class")
    circuit_until = (row or {}).get("circuit_open_until")

    if latency is not None:
        ewma = float(latency) if ewma is None else float(ewma) * 0.8 + latency * 0.2

    if kind == "success":
        successes += 1
        streak = 0
        last_success = current
        last_error = None
        last_error_class = None
        circuit_until = None
    elif kind == "neutral":
        neutral += 1
    else:
        failures += 1
        streak += 1
        last_failure = current
        last_error = error or status[:500]
        last_error_class = error_class
        threshold = _env_int(
            "OPENCRAWL_PROVIDER_CIRCUIT_FAILURES",
            3,
            minimum=2,
            maximum=20,
        )
        if streak >= threshold:
            base = _env_int(
                "OPENCRAWL_PROVIDER_CIRCUIT_COOLDOWN_SECONDS",
                45,
                minimum=5,
                maximum=900,
            )
            maximum = _env_int(
                "OPENCRAWL_PROVIDER_CIRCUIT_MAX_COOLDOWN_SECONDS",
                300,
                minimum=30,
                maximum=3600,
            )
            exponent = min(4, streak - threshold)
            cooldown = min(maximum, base * (2**exponent))
            proposed = current + timedelta(seconds=cooldown)
            if circuit_until is None or circuit_until < proposed:
                circuit_until = proposed

    cur.execute(
        """
        INSERT INTO ih_provider_reliability(
            provider,successes,failures,neutral,consecutive_failures,
            ewma_latency_ms,last_success_at,last_failure_at,last_error,
            last_error_class,circuit_open_until,updated_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (provider) DO UPDATE SET
            successes=EXCLUDED.successes,
            failures=EXCLUDED.failures,
            neutral=EXCLUDED.neutral,
            consecutive_failures=EXCLUDED.consecutive_failures,
            ewma_latency_ms=EXCLUDED.ewma_latency_ms,
            last_success_at=EXCLUDED.last_success_at,
            last_failure_at=EXCLUDED.last_failure_at,
            last_error=EXCLUDED.last_error,
            last_error_class=EXCLUDED.last_error_class,
            circuit_open_until=EXCLUDED.circuit_open_until,
            updated_at=EXCLUDED.updated_at
        """,
        (
            provider,
            successes,
            failures,
            neutral,
            streak,
            ewma,
            last_success,
            last_failure,
            last_error,
            last_error_class,
            circuit_until,
            current,
        ),
    )


class SharedProviderReliabilityStore:
    """Read/reset access to provider reliability shared through the control database."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn if dsn is not None else _selected_dsn()
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.dsn and _shared_enabled())

    def _connect(self):
        if not self.dsn:
            raise RuntimeError("provider reliability database is not configured")
        options: dict[str, Any] = {
            "row_factory": dict_row,
            "connect_timeout": _env_int(
                "OPENCRAWL_DB_CONNECT_TIMEOUT_SECONDS",
                5,
                minimum=1,
                maximum=30,
            ),
        }
        if "pooler.supabase.com" in self.dsn:
            options["prepare_threshold"] = None
        return psycopg.connect(self.dsn, **options)

    def ensure_schema(self) -> None:
        if not self.configured or self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._connect() as conn, conn.cursor() as cur:
                ensure_provider_reliability_schema(cur)
                conn.commit()
            self._schema_ready = True

    @staticmethod
    def _timestamp(value: Any) -> float | None:
        if isinstance(value, datetime):
            return value.timestamp()
        return None

    def snapshot(self, provider: str | None = None) -> dict[str, dict[str, Any]]:
        if not self.configured:
            return {}
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            if provider:
                cur.execute(
                    "SELECT * FROM ih_provider_reliability WHERE provider=%s",
                    (provider.strip().lower(),),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM ih_provider_reliability
                    ORDER BY updated_at DESC
                    LIMIT 250
                    """
                )
            rows = cur.fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            name = str(row["provider"])
            result[name] = {
                "provider": name,
                "successes": int(row.get("successes") or 0),
                "failures": int(row.get("failures") or 0),
                "neutral": int(row.get("neutral") or 0),
                "consecutive_failures": int(row.get("consecutive_failures") or 0),
                "ewma_latency_ms": (
                    float(row["ewma_latency_ms"])
                    if row.get("ewma_latency_ms") is not None
                    else None
                ),
                "last_success_at": self._timestamp(row.get("last_success_at")),
                "last_failure_at": self._timestamp(row.get("last_failure_at")),
                "last_error": row.get("last_error"),
                "last_error_class": row.get("last_error_class"),
                "circuit_open_until": self._timestamp(row.get("circuit_open_until")) or 0.0,
                "updated_at": self._timestamp(row.get("updated_at")),
            }
        return result

    def reset(self, provider: str | None = None) -> None:
        if not self.configured:
            return
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            if provider:
                cur.execute(
                    "DELETE FROM ih_provider_reliability WHERE provider=%s",
                    (provider.strip().lower(),),
                )
            else:
                cur.execute("DELETE FROM ih_provider_reliability")
            conn.commit()


shared_provider_reliability = SharedProviderReliabilityStore()
