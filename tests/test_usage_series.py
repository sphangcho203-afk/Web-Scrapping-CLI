from datetime import UTC, datetime, timedelta

from internet_hands.usage_intelligence import complete_series, usage_bounds


def test_hourly_rolling_window_preserves_partial_edges_and_quiet_hours():
    end = datetime(2026, 9, 30, 12, 30, tzinfo=UTC)
    start, _, granularity = usage_bounds("24h", end)
    assert end - start == timedelta(hours=24) and granularity == "hour"
    rows = complete_series([{"bucket": end.replace(minute=0), "requests": 2,
        "succeeded": 1, "failed": 0, "pending": 1, "credits": 9,
        "avg_latency_ms": 250, "latency_samples": 1}], start, end, granularity)
    assert len(rows) == 25 and rows[0]["partial"] and rows[-1]["partial"]
    assert rows[0]["bucket_start"] == start and rows[-1]["bucket_end"] == end
    assert sum(r["requests"] for r in rows) == 2 and sum(r["credits"] for r in rows) == 9
    assert rows[1]["requests"] == 0 and rows[1]["avg_latency_ms"] is None
    assert rows[-1]["success_rate"] == 100


def test_daily_series_uses_utc_and_no_extra_empty_bucket_at_exact_boundary():
    end = datetime(2026, 9, 30, tzinfo=UTC)
    start, _, granularity = usage_bounds("7d", end)
    rows = complete_series([], start, end, granularity)
    assert len(rows) == 7 and all(not r["partial"] for r in rows)
    assert all(r["success_rate"] is None for r in rows)
    assert rows[-1]["bucket_end"] == end


def test_pending_only_bucket_has_no_completed_success_rate():
    end = datetime(2026, 9, 30, tzinfo=UTC)
    start = end - timedelta(days=1)
    rows = complete_series([{"bucket": start, "requests": 2, "pending": 2,
        "succeeded": 0, "failed": 0, "credits": 0, "latency_samples": 0,
        "avg_latency_ms": None}], start, end, "day")
    assert rows[0]["success_rate"] is None
