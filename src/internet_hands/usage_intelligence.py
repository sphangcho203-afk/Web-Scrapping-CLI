from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .control_store import ControlStore

WINDOWS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30), "90d": timedelta(days=90)}


def normalize_window(value: str) -> str:
    value = (value or "30d").lower().strip()
    if value not in WINDOWS:
        raise ValueError(f"unsupported usage window: {value}")
    return value


def usage_bounds(window: str, as_of: datetime | None = None) -> tuple[datetime, datetime, str]:
    window = normalize_window(window)
    end = as_of or datetime.now(UTC)
    if end.tzinfo is None:
        raise ValueError("Usage snapshot time must include a timezone.")
    end = end.astimezone(UTC)
    return end - WINDOWS[window], end, "hour" if window == "24h" else "day"


def complete_series(rows: list[dict], start: datetime, end: datetime, granularity: str) -> list[dict]:
    """Fill ledger-free buckets with zero counts; absent measurements stay null."""
    step = timedelta(hours=1) if granularity == "hour" else timedelta(days=1)
    bucket = start.replace(minute=0, second=0, microsecond=0)
    if granularity == "day":
        bucket = bucket.replace(hour=0)
    observed = {row["bucket"]: row for row in rows}
    series = []
    while bucket < end:
        row = {"bucket": bucket, "requests": 0, "succeeded": 0, "failed": 0, "pending": 0,
               "credits": 0, "avg_latency_ms": None, "latency_samples": 0,
               **observed.get(bucket, {})}
        completed = row["succeeded"] + row["failed"]
        row["success_rate"] = round(100 * row["succeeded"] / completed, 2) if completed else None
        row["bucket_start"], row["bucket_end"] = max(start, bucket), min(end, bucket + step)
        row["partial"] = row["bucket_start"] != bucket or row["bucket_end"] != bucket + step
        series.append(row)
        bucket += step
    return series


class UsageIntelligence:
    """Read-only usage analytics over the canonical metering ledger."""

    def __init__(self, store: ControlStore) -> None:
        self.store = store

    def run_detail(self, user_id: str, request_id: str) -> dict[str, Any] | None:
        """Return one user-owned metered run with its inspectable execution metadata."""
        request_id = (request_id or "").strip()
        if not request_id:
            return None
        self.store.ensure_schema()
        with self.store._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.request_id,e.tool_ref,e.capability,e.provider,e.status,
                       e.credits_charged,e.latency_ms,e.input_bytes,e.output_bytes,
                       e.metadata,e.created_at,
                       k.id AS api_key_id,k.name AS api_key_name,k.prefix AS api_key_prefix,
                       k.environment AS api_key_environment
                FROM ih_usage_events e
                LEFT JOIN ih_api_keys k ON k.id=e.api_key_id AND k.user_id=e.user_id
                WHERE e.user_id=%s AND e.request_id=%s
                LIMIT 1
                """,
                (user_id, request_id),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def snapshot(self, user_id: str, *, window: str = "30d", recent_limit: int = 12,
                 as_of: datetime | None = None) -> dict[str, Any]:
        window = normalize_window(window)
        start, end, granularity = usage_bounds(window, as_of)
        recent_limit = max(1, min(int(recent_limit), 50))
        self.store.ensure_schema()
        account = self.store.account_snapshot(user_id)
        with self.store._connect() as conn, conn.cursor() as cur:
            # Every aggregate and recent row sees one consistent ledger snapshot.
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            params = (user_id, start, end)
            cur.execute(
                """
                SELECT count(*)::int AS requests,
                       count(*) FILTER (WHERE status='ok')::int AS succeeded,
                       count(*) FILTER (WHERE status IN ('accepted','reserved'))::int AS pending,
                       count(*) FILTER (WHERE status NOT IN ('ok','accepted','reserved'))::int AS failed,
                       COALESCE(sum(credits_charged),0)::int AS credits,
                       count(latency_ms)::int AS latency_samples,
                       avg(latency_ms)::int AS avg_latency_ms,
                       percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
                           FILTER (WHERE latency_ms IS NOT NULL)::int AS p95_latency_ms
                FROM ih_usage_events
                WHERE user_id=%s AND created_at >= %s AND created_at < %s
                """,
                params,
            )
            totals = dict(cur.fetchone())
            completed = int(totals["succeeded"] or 0) + int(totals["failed"] or 0)
            totals["success_rate"] = round(100.0 * int(totals["succeeded"] or 0) / completed, 2) if completed else None

            cur.execute(
                """
                SELECT date_trunc(%s,created_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AS bucket,
                       count(*)::int AS requests,
                       count(*) FILTER (WHERE status='ok')::int AS succeeded,
                       count(*) FILTER (WHERE status IN ('accepted','reserved'))::int AS pending,
                       count(*) FILTER (WHERE status NOT IN ('ok','accepted','reserved'))::int AS failed,
                       COALESCE(sum(credits_charged),0)::int AS credits,
                       count(latency_ms)::int AS latency_samples,
                       avg(latency_ms)::int AS avg_latency_ms
                FROM ih_usage_events
                WHERE user_id=%s AND created_at >= %s AND created_at < %s
                GROUP BY 1 ORDER BY 1
                """,
                (granularity, *params),
            )
            series = complete_series([dict(row) for row in cur.fetchall()], start, end, granularity)

            def breakdown(column: str, limit: int = 10) -> list[dict[str, Any]]:
                cur.execute(
                    f"""
                    SELECT COALESCE({column},'unattributed') AS name, count(*)::int AS requests,
                           COALESCE(sum(credits_charged),0)::int AS credits,
                           avg(latency_ms)::int AS avg_latency_ms
                    FROM ih_usage_events
                    WHERE user_id=%s AND created_at >= %s AND created_at < %s
                    GROUP BY 1 ORDER BY requests DESC, credits DESC, name LIMIT %s
                    """,
                    (*params, limit),
                )
                return [dict(row) for row in cur.fetchall()]

            by_tool = breakdown("tool_ref")
            remaining_requests = totals["requests"] - sum(row["requests"] for row in by_tool)
            if remaining_requests:
                by_tool.append({"name": "Other operations", "is_remainder": True,
                                "requests": remaining_requests,
                                "credits": totals["credits"] - sum(row["credits"] for row in by_tool),
                                "avg_latency_ms": None})
            by_provider = breakdown("provider")
            by_status = breakdown("status")
            remaining_statuses = totals["requests"] - sum(row["requests"] for row in by_status)
            if remaining_statuses:
                by_status.append({"name": "Other outcomes", "is_remainder": True,
                                  "requests": remaining_statuses,
                                  "credits": totals["credits"] - sum(row["credits"] for row in by_status),
                                  "avg_latency_ms": None})

            cur.execute(
                """
                SELECT request_id,tool_ref,capability,provider,status,credits_charged,latency_ms,created_at
                FROM ih_usage_events
                WHERE user_id=%s AND created_at >= %s AND created_at < %s
                ORDER BY created_at DESC LIMIT %s
                """,
                (*params, recent_limit),
            )
            recent = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT request_id,tool_ref,capability,provider,status,credits_charged,latency_ms,created_at
                FROM ih_usage_events
                WHERE user_id=%s AND created_at >= %s AND created_at < %s
                  AND status NOT IN ('ok','accepted','reserved')
                ORDER BY created_at DESC LIMIT %s
                """,
                (*params, recent_limit),
            )
            failures = [dict(row) for row in cur.fetchall()]

        return {
            "window": window,
            "generated_at": end,
            "range": {"start": start, "end": end, "timezone": "UTC", "granularity": granularity},
            "available_windows": list(WINDOWS),
            "account": account,
            "totals": totals,
            "series": series,
            "breakdowns": {"tool": by_tool, "provider": by_provider, "status": by_status},
            "recent_runs": recent,
            "recent_failures": failures,
        }
