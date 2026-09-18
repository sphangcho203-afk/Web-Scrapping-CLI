from __future__ import annotations

from datetime import timedelta
from typing import Any

from .control_store import ControlStore

WINDOWS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30), "90d": timedelta(days=90)}


def normalize_window(value: str) -> str:
    value = (value or "30d").lower().strip()
    if value not in WINDOWS:
        raise ValueError(f"unsupported usage window: {value}")
    return value


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

    def snapshot(self, user_id: str, *, window: str = "30d", recent_limit: int = 12) -> dict[str, Any]:
        window = normalize_window(window)
        interval = WINDOWS[window]
        seconds = int(interval.total_seconds())
        recent_limit = max(1, min(int(recent_limit), 50))
        self.store.ensure_schema()
        account = self.store.account_snapshot(user_id)
        with self.store._connect() as conn, conn.cursor() as cur:
            params = (user_id, seconds)
            cur.execute(
                """
                SELECT count(*)::int AS requests,
                       count(*) FILTER (WHERE status='ok')::int AS succeeded,
                       count(*) FILTER (WHERE status NOT IN ('ok','accepted'))::int AS failed,
                       COALESCE(sum(credits_charged),0)::int AS credits,
                       COALESCE(avg(latency_ms) FILTER (WHERE latency_ms IS NOT NULL),0)::int AS avg_latency_ms,
                       COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
                           FILTER (WHERE latency_ms IS NOT NULL),0)::int AS p95_latency_ms
                FROM ih_usage_events
                WHERE user_id=%s AND created_at >= now()-(%s * interval '1 second')
                """,
                params,
            )
            totals = dict(cur.fetchone())
            requests = int(totals["requests"] or 0)
            totals["success_rate"] = round(100.0 * int(totals["succeeded"] or 0) / requests, 2) if requests else None

            cur.execute(
                """
                SELECT date_trunc('day',created_at)::date AS bucket,
                       count(*)::int AS requests,
                       count(*) FILTER (WHERE status='ok')::int AS succeeded,
                       COALESCE(sum(credits_charged),0)::int AS credits,
                       COALESCE(avg(latency_ms) FILTER (WHERE latency_ms IS NOT NULL),0)::int AS avg_latency_ms
                FROM ih_usage_events
                WHERE user_id=%s AND created_at >= now()-(%s * interval '1 second')
                GROUP BY 1 ORDER BY 1
                """,
                params,
            )
            series = [dict(row) for row in cur.fetchall()]

            def breakdown(column: str, limit: int = 10) -> list[dict[str, Any]]:
                cur.execute(
                    f"""
                    SELECT COALESCE({column},'unattributed') AS name, count(*)::int AS requests,
                           COALESCE(sum(credits_charged),0)::int AS credits,
                           COALESCE(avg(latency_ms) FILTER (WHERE latency_ms IS NOT NULL),0)::int AS avg_latency_ms
                    FROM ih_usage_events
                    WHERE user_id=%s AND created_at >= now()-(%s * interval '1 second')
                    GROUP BY 1 ORDER BY requests DESC, credits DESC LIMIT %s
                    """,
                    (user_id, seconds, limit),
                )
                return [dict(row) for row in cur.fetchall()]

            by_tool = breakdown("tool_ref")
            by_provider = breakdown("provider")
            by_status = breakdown("status")

            cur.execute(
                """
                SELECT request_id,tool_ref,capability,provider,status,credits_charged,latency_ms,created_at
                FROM ih_usage_events
                WHERE user_id=%s AND created_at >= now()-(%s * interval '1 second')
                ORDER BY created_at DESC LIMIT %s
                """,
                (user_id, seconds, recent_limit),
            )
            recent = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT request_id,tool_ref,capability,provider,status,credits_charged,latency_ms,created_at
                FROM ih_usage_events
                WHERE user_id=%s AND created_at >= now()-(%s * interval '1 second')
                  AND status NOT IN ('ok','accepted')
                ORDER BY created_at DESC LIMIT %s
                """,
                (user_id, seconds, recent_limit),
            )
            failures = [dict(row) for row in cur.fetchall()]

        return {
            "window": window,
            "available_windows": list(WINDOWS),
            "account": account,
            "totals": totals,
            "series": series,
            "breakdowns": {"tool": by_tool, "provider": by_provider, "status": by_status},
            "recent_runs": recent,
            "recent_failures": failures,
        }
