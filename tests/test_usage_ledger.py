import uuid
from datetime import UTC, datetime, timedelta

from test_crawl_runs import runs  # noqa: F401 -- shared isolated PostgreSQL fixture

from internet_hands.usage_intelligence import UsageIntelligence


def test_series_totals_are_owned_consistent_and_zero_filled(request):
    jobs, identity = request.getfixturevalue("runs")
    control = jobs.control
    end = datetime(2026, 9, 30, 12, 30, tzinfo=UTC)
    foreign = "usage_foreign_" + uuid.uuid4().hex
    with control._connect() as conn, conn.cursor() as cur:
        for hours, status, credits, latency in [(23, "ok", 7, 100), (1, "failed", 3, 300), (0, "accepted", 0, None), (25, "ok", 999, 999)]:
            cur.execute("""INSERT INTO ih_usage_events(id,user_id,request_id,tool_ref,status,credits_charged,latency_ms,created_at)
                VALUES (%s,%s,%s,'playground:crawl',%s,%s,%s,%s)""",
                (uuid.uuid4().hex, identity.user_id, uuid.uuid4().hex, status, credits, latency, end - timedelta(hours=hours, minutes=1)))
        # A future event must not leak into a bounded snapshot.
        cur.execute("""INSERT INTO ih_usage_events(id,user_id,request_id,status,credits_charged,created_at)
            VALUES (%s,%s,%s,'ok',888,%s)""", (uuid.uuid4().hex, identity.user_id, uuid.uuid4().hex, end + timedelta(seconds=1)))
        cur.execute("INSERT INTO ih_users(id,email) VALUES (%s,%s)", (foreign, foreign + "@test.invalid"))
        cur.execute("""INSERT INTO ih_usage_events(id,user_id,request_id,status,credits_charged,created_at)
            VALUES (%s,%s,%s,'ok',777,%s)""", (uuid.uuid4().hex, foreign, uuid.uuid4().hex, end - timedelta(seconds=1)))
    try:
        snapshot = UsageIntelligence(control).snapshot(identity.user_id, window="24h", as_of=end)
    finally:
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM ih_users WHERE id=%s", (foreign,))
    totals, series = snapshot["totals"], snapshot["series"]
    assert totals["requests"] == 3 and totals["credits"] == 10 and totals["pending"] == 1
    assert totals["success_rate"] == 50 and totals["latency_samples"] == 2
    assert len(series) == 25
    for field in ("requests", "credits", "succeeded", "failed", "pending"):
        assert sum(r[field] for r in series) == totals[field]
    assert snapshot["range"]["timezone"] == "UTC" and snapshot["range"]["end"] == end


def test_empty_ledger_and_top_operation_remainder(request):
    jobs, identity = request.getfixturevalue("runs")
    control = jobs.control
    end = datetime.now(UTC)
    empty = UsageIntelligence(control).snapshot(identity.user_id, window="7d", as_of=end)
    assert empty["totals"]["success_rate"] is None and empty["totals"]["p95_latency_ms"] is None
    assert all(row["requests"] == 0 for row in empty["series"])
    with control._connect() as conn, conn.cursor() as cur:
        for index in range(12):
            cur.execute("""INSERT INTO ih_usage_events(id,user_id,request_id,tool_ref,status,credits_charged,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""", (uuid.uuid4().hex, identity.user_id, uuid.uuid4().hex,
                f"operation:{index}", f"failure:{index}", index + 1, end - timedelta(seconds=1)))
    snapshot = UsageIntelligence(control).snapshot(identity.user_id, as_of=end)
    tools = snapshot["breakdowns"]["tool"]
    assert len(tools) == 11 and tools[-1]["is_remainder"]
    assert sum(r["requests"] for r in tools) == 12 and sum(r["credits"] for r in tools) == 78

    statuses = snapshot["breakdowns"]["status"]
    assert len(statuses) == 11 and statuses[-1]["is_remainder"]
    assert sum(r["requests"] for r in statuses) == 12
