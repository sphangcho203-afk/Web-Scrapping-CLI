from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from .control_store import ControlStore
from .fetcher import health_check

router = APIRouter()
store = ControlStore()

MAX_BATCH = 10
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_TIMEOUT_SECONDS = 20.0


def _cron_authorized(authorization: str | None) -> None:
    secret = os.getenv("CRON_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="monitor scheduler is not configured")
    if authorization != f"Bearer {secret}":
        raise HTTPException(status_code=401, detail="unauthorized")


def _claim_due_monitors(limit: int = MAX_BATCH) -> list[dict[str, Any]]:
    """Atomically lease due work by advancing next_check_at before network I/O.

    FOR UPDATE SKIP LOCKED prevents overlapping scheduler invocations from claiming the
    same monitor. Advancing next_check_at is the lease: a crashed invocation will not
    hot-loop the target and the monitor becomes eligible again at its next interval.
    """
    bounded = max(1, min(int(limit), MAX_BATCH))
    with store._connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH due AS (
                SELECT id
                FROM ih_monitors
                WHERE enabled = true
                  AND (next_check_at IS NULL OR next_check_at <= now())
                ORDER BY next_check_at NULLS FIRST, created_at
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            UPDATE ih_monitors AS monitor
            SET next_check_at = now() + (monitor.interval_minutes || ' minutes')::interval,
                updated_at = now()
            FROM due
            WHERE monitor.id = due.id
            RETURNING monitor.*
            """,
            (bounded,),
        )
        rows = [dict(row) for row in cur.fetchall()]
        conn.commit()
    return rows


def _timeout_for(monitor: dict[str, Any]) -> float:
    config = monitor.get("config") or {}
    try:
        requested = float(config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        requested = DEFAULT_TIMEOUT_SECONDS
    return max(1.0, min(requested, MAX_TIMEOUT_SECONDS))


async def _execute_monitor(monitor: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    monitor_type = str(monitor.get("type") or "")
    target = str(monitor.get("target") or "")
    status = "failed"
    http_status: int | None = None
    summary: str

    try:
        if monitor_type not in {"web", "api", "mcp"}:
            raise ValueError(f"monitor type {monitor_type!r} has no bounded executor")
        result = await health_check(target, timeout=_timeout_for(monitor))
        http_status = result.status_code
        if result.ok:
            status = "healthy"
            summary = f"HTTP {http_status}" if http_status is not None else "target healthy"
        else:
            summary = result.error or (
                f"HTTP {http_status}" if http_status is not None else "target unhealthy"
            )
    except Exception as exc:  # noqa: BLE001 -- execution failures are persisted as data
        summary = f"{type(exc).__name__}: {exc}"

    latency_ms = max(0, round((time.perf_counter() - started) * 1000))
    checked_at = datetime.now(UTC)
    run_id = f"mrun_{uuid.uuid4().hex}"
    summary = summary[:1000]

    with store._connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ih_monitor_runs
                (id, monitor_id, status, latency_ms, http_status, summary, credits_charged)
            VALUES (%s, %s, %s, %s, %s, %s, 0)
            """,
            (run_id, monitor["id"], status, latency_ms, http_status, summary),
        )
        cur.execute(
            """
            UPDATE ih_monitors
            SET last_status=%s, last_checked_at=%s, updated_at=now()
            WHERE id=%s
            """,
            (status, checked_at, monitor["id"]),
        )
        conn.commit()

    return {
        "id": run_id,
        "monitor_id": monitor["id"],
        "status": status,
        "http_status": http_status,
        "latency_ms": latency_ms,
        "summary": summary,
    }


async def run_due_monitors(limit: int = MAX_BATCH) -> dict[str, Any]:
    claimed = _claim_due_monitors(limit)
    runs: list[dict[str, Any]] = []
    for monitor in claimed:
        # Deliberately isolate each monitor so one target cannot abort the batch.
        try:
            runs.append(await _execute_monitor(monitor))
        except Exception as exc:  # noqa: BLE001 -- batch isolation boundary
            runs.append(
                {
                    "monitor_id": monitor.get("id"),
                    "status": "executor_error",
                    "summary": f"{type(exc).__name__}: {exc}"[:1000],
                }
            )
    return {"claimed": len(claimed), "completed": len(runs), "runs": runs}


@router.get("/api/internal/monitors/tick")
async def monitor_tick(authorization: str | None = Header(default=None)):
    """Vercel Cron entrypoint. CRON_SECRET is required; no user session can invoke it."""
    _cron_authorized(authorization)
    return await run_due_monitors()
