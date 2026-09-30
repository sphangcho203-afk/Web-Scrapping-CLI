"""Content checks use real owned jobs, PostgreSQL transactions and wallet settlement."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from internet_hands import crawler
from internet_hands.control_store import ControlStore
from internet_hands.crawl_run_worker import dispatch_run
from internet_hands.crawl_runs import RunStore
from internet_hands.models import FetchResult
from internet_hands.monitor_lifecycle import validate_monitor_spec


def test_content_monitor_requires_explicit_billing_key():
    with pytest.raises(ValueError, match="API key"):
        validate_monitor_spec({"name": "Pricing", "type": "content", "target": "https://example.com/pricing"})
    spec = validate_monitor_spec({"name": "Pricing", "type": "content", "target": "https://example.com/pricing", "config": {"api_key_id": "key_test"}})
    assert spec["type"] == "content" and spec["config"] == {"api_key_id": "key_test"}


@pytest.fixture
def content_monitor(monkeypatch):
    dsn = os.getenv("OPENCRAWL_TEST_DATASET_DSN")
    if not dsn:
        pytest.skip("Requires an isolated PostgreSQL test database.")
    control = ControlStore(dsn)
    control.ensure_schema()
    owner = "monitor_" + uuid.uuid4().hex
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO ih_users(id,email) VALUES (%s,%s)", (owner, owner + "@test.invalid"))
        cur.execute("INSERT INTO ih_wallets(user_id,monthly_credits) VALUES (%s,10000)", (owner,))
    key = control.create_api_key(user_id=owner, name="Monitoring", prefix="oc_test", key_hash=uuid.uuid4().hex, scopes=["mcp:execute"], environment="live")
    monitor = control.create_monitor(user_id=owner, name="Pricing", monitor_type="content", target="https://example.com/pricing", interval_minutes=60, config={"api_key_id": key["id"]})
    capture = {"text": "Plan costs $20.", "status": 200}

    async def fetch(url, **kwargs):
        return FetchResult(request_url=url, final_url=url, status_code=capture["status"], headers={}, content_type="text/html", content_length=100, sha256="a" * 64, elapsed_ms=1, captured_at=datetime.now(UTC), body_text=f'<title>Pricing</title><p>{capture["text"]}</p>')

    async def robots(url):
        from urllib.robotparser import RobotFileParser
        parser = RobotFileParser()
        parser.parse(["User-agent: *", "Allow: /"])
        return parser

    monkeypatch.setattr(crawler, "fetch_url", fetch)
    monkeypatch.setattr(crawler, "_robots_for", robots)
    monkeypatch.setattr(crawler, "validate_public_http_url", lambda _: None)
    try:
        yield control, owner, monitor, key, capture
    finally:
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM ih_users WHERE id=%s", (owner,))


def due(control, monitor):
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_monitors SET next_check_at=now()-interval '1 minute' WHERE id=%s", (monitor["id"],))


def queue(control):
    from internet_hands.content_monitors import queue_due_content_checks
    return queue_due_content_checks(control)


async def check(control, monitor):
    due(control, monitor)
    assert queue(control)["queued"] == 1
    assert (await dispatch_run(RunStore(control)))["processed"] == 1


async def test_baseline_unchanged_change_and_failure_are_atomic_and_metered(content_monitor):
    control, owner, monitor, key, capture = content_monitor
    await check(control, monitor)
    baseline = control.get_monitor(owner, monitor["id"])
    assert baseline["last_status"] == "baseline" and baseline["baseline_dataset_id"]
    capture["text"] = "Plan   costs\n$20."
    await check(control, monitor)
    unchanged = control.get_monitor(owner, monitor["id"])
    assert unchanged["last_status"] == "unchanged"
    assert unchanged["baseline_dataset_id"] == baseline["baseline_dataset_id"]
    capture["text"] = "Plan costs $30."
    await check(control, monitor)
    changed = control.get_monitor(owner, monitor["id"])
    assert changed["last_status"] == "changed"
    assert changed["baseline_dataset_id"] != baseline["baseline_dataset_id"]
    capture["status"] = 403
    await check(control, monitor)
    failed = control.get_monitor(owner, monitor["id"])
    assert failed["last_status"] == "failed" and failed["baseline_hash"] == changed["baseline_hash"]
    assert failed["runs"][0]["credits_charged"] == 0
    assert failed["runs"][0]["dataset_id"] is None
    assert failed["runs"][1]["diff"]["previous_dataset_id"] == baseline["baseline_dataset_id"]
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM ih_datasets WHERE user_id=%s", (owner,))
        assert cur.fetchone()["n"] == 2
        cur.execute("SELECT reserved_credits,monthly_credits FROM ih_wallets WHERE user_id=%s", (owner,))
        wallet = cur.fetchone()
        assert wallet["reserved_credits"] == 0
        assert 10000-wallet["monthly_credits"] == sum(r["credits_charged"] for r in failed["runs"])
        assert all(r["credits_charged"] > 0 for r in failed["runs"][1:])
        cur.execute("SELECT api_key_id FROM ih_usage_events WHERE user_id=%s", (owner,))
        assert all(r["api_key_id"] == key["id"] for r in cur.fetchall())


async def test_overlapping_ticks_do_not_queue_or_reserve_duplicate_checks(content_monitor):
    control, owner, monitor, _, _ = content_monitor
    due(control, monitor)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: queue(control), range(4)))
    assert sum(r["queued"] for r in results) == 1
    due(control, monitor)
    assert queue(control)["queued"] == 0  # still one active check even when overdue
    assert (await dispatch_run(RunStore(control)))["processed"] == 1
    assert len(control.get_monitor(owner, monitor["id"])["runs"]) == 1


@pytest.mark.parametrize("mutation", ["pause", "edit", "revoke", "delete"])
async def test_pending_checks_are_fenced_before_network_and_release_reservation(content_monitor, monkeypatch, mutation):
    control, owner, monitor, key, _ = content_monitor
    due(control, monitor)
    assert queue(control)["queued"] == 1
    with control._connect() as conn, conn.cursor() as cur:
        if mutation == "pause":
            cur.execute("UPDATE ih_monitors SET enabled=false WHERE id=%s", (monitor["id"],))
        elif mutation == "edit":
            cur.execute("UPDATE ih_monitors SET content_version=content_version+1 WHERE id=%s", (monitor["id"],))
        elif mutation == "revoke":
            cur.execute("UPDATE ih_api_keys SET revoked_at=now() WHERE id=%s", (key["id"],))
        else:
            cur.execute("DELETE FROM ih_monitors WHERE id=%s", (monitor["id"],))
    async def forbidden(*args, **kwargs):
        pytest.fail("A stale or unauthorized monitor must not fetch")
    monkeypatch.setattr(crawler, "fetch_url", forbidden)
    assert (await dispatch_run(RunStore(control)))["processed"] == 1
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT reserved_credits,monthly_credits FROM ih_wallets WHERE user_id=%s", (owner,))
        wallet = cur.fetchone()
        assert wallet["reserved_credits"] == 0 and wallet["monthly_credits"] == 10000
        cur.execute("SELECT count(*) AS n FROM ih_datasets WHERE user_id=%s", (owner,))
        assert cur.fetchone()["n"] == 0


async def test_revoked_key_blocks_scheduling_without_reserving(content_monitor):
    control, owner, monitor, key, _ = content_monitor
    control.revoke_api_key(owner, key["id"])
    due(control, monitor)
    assert queue(control)["queued"] == 0
    row = control.get_monitor(owner, monitor["id"])
    assert row["last_status"] == "blocked" and row["runs"][0]["credits_charged"] == 0


async def test_edit_during_capture_cannot_publish_old_baseline(content_monitor):
    control, owner, monitor, _, _ = content_monitor
    due(control, monitor)
    assert queue(control)["queued"] == 1
    jobs = RunStore(control)
    job = jobs.claim()
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_monitors SET content_version=content_version+1,target='https://example.com/new' WHERE id=%s", (monitor["id"],))
    assert jobs.finish(job, "completed", {"pages": [{"url": monitor["target"], "status_code": 200, "text": "Old price"}]}, {})
    row = control.get_monitor(owner, monitor["id"])
    assert row["baseline_hash"] is None
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM ih_datasets WHERE user_id=%s", (owner,))
        assert cur.fetchone()["n"] == 0


async def test_dataset_failure_rolls_back_baseline_history_and_wallet(content_monitor, monkeypatch):
    from internet_hands.datasets import DatasetStore
    control, owner, monitor, _, _ = content_monitor
    due(control, monitor)
    queue(control)
    jobs = RunStore(control)
    job = jobs.claim()
    output = {"pages": [{"url": monitor["target"], "status_code": 200, "text": "New price"}]}
    original = DatasetStore.save
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("interrupted after insert")
    monkeypatch.setattr(DatasetStore, "save", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        jobs.finish(job, "completed", output, {})
    row = control.get_monitor(owner, monitor["id"])
    assert row["baseline_hash"] is None and row["runs"] == []
    monkeypatch.setattr(DatasetStore, "save", original)
    assert jobs.finish(job, "completed", output, {})
    assert jobs.finish(job, "completed", output, {}) is False
    row = control.get_monitor(owner, monitor["id"])
    assert len(row["runs"]) == 1 and row["baseline_dataset_id"]


async def test_replacement_worker_fences_old_baseline_and_settles_once(content_monitor):
    control, owner, monitor, _, _ = content_monitor
    due(control, monitor)
    queue(control)
    jobs = RunStore(control)
    first = jobs.claim()
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_crawl_runs SET lease_until=now()-interval '1 second' WHERE id=%s", (first["id"],))
    second = jobs.claim()
    output = {"pages": [{"url": monitor["target"], "status_code": 200, "text": "New price"}]}
    assert jobs.finish(first, "completed", output, {}) is False
    assert jobs.finish(second, "completed", output, {})
    assert jobs.finish(second, "completed", output, {}) is False
    row = control.get_monitor(owner, monitor["id"])
    assert len(row["runs"]) == 1 and row["baseline_dataset_id"]
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT reserved_credits FROM ih_wallets WHERE user_id=%s", (owner,))
        assert cur.fetchone()["reserved_credits"] == 0


async def test_api_ownership_config_fencing_and_scheduler_to_worker(content_monitor, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from internet_hands import control_api, crawl_run_api, monitor_executor, monitor_lifecycle
    control, owner, monitor, key, _ = content_monitor
    monkeypatch.setattr(control_api, "store", control)
    monkeypatch.setattr(monitor_lifecycle, "store", control)
    monkeypatch.setattr(monitor_executor, "store", control)
    monkeypatch.setattr(crawl_run_api, "runs", RunStore(control))
    def session(request):
        return {"id": request.headers.get("x-test-owner", owner), "email_verified": True}
    monkeypatch.setattr(control_api, "_require_user", session)
    monkeypatch.setattr(monitor_lifecycle, "_require_user", session)
    monkeypatch.setenv("CRON_SECRET", "isolated-test-secret")
    app = FastAPI()
    for router in [control_api.router, monitor_lifecycle.router, monitor_executor.router, crawl_run_api.router]:
        app.include_router(router)
    with TestClient(app) as client:
        path = "/api/monitors/" + monitor["id"]
        assert client.get(path + "/history", headers={"x-test-owner": "foreign"}).status_code == 404
        assert client.patch(path, json={"name": "Foreign"}, headers={"x-test-owner": "foreign"}).status_code == 404
        spec = {"name": "Watch", "type": "content", "target": monitor["target"], "config": {"api_key_id": key["id"]}}
        assert client.post("/api/monitors/validate", json=spec, headers={"x-test-owner": "foreign"}).status_code == 403
        assert client.post("/api/monitors", json=spec, headers={"x-test-owner": "foreign"}).status_code == 403
        assert client.get("/api/internal/monitors/tick").status_code == 401
        auth = {"authorization": "Bearer isolated-test-secret"}
        due(control, monitor)
        assert client.get("/api/internal/monitors/tick", headers=auth).json()["content_checks"]["queued"] == 1
        assert client.get(path).json()["pending_run"]["status"] == "queued"
        assert client.get("/api/internal/crawl-runs/tick", headers=auth).json()["processed"] == 1
        baseline = client.get(path).json()
        assert baseline["last_status"] == "baseline"
        # Sending unchanged fields while renaming preserves the baseline.
        renamed = client.patch(path, json={**spec, "name": "Renamed"}).json()
        assert renamed["baseline_hash"] == baseline["baseline_hash"]
        changed = client.patch(path, json={"target": "https://example.com/new", "interval_minutes": 15}).json()
        assert changed["baseline_hash"] is None
        assert changed["content_version"] == baseline["content_version"] + 1
        assert client.post("/api/monitors", json={"name": "Invalid", "type": "content", "target": "file:///etc/passwd"}).status_code == 422


async def test_truncated_content_is_not_compared_or_charged(content_monitor):
    control, owner, monitor, _, capture = content_monitor
    await check(control, monitor)
    baseline = control.get_monitor(owner, monitor["id"])
    capture["text"] = "x" * 60_000
    await check(control, monitor)
    failed = control.get_monitor(owner, monitor["id"])
    assert failed["last_status"] == "failed" and failed["baseline_hash"] == baseline["baseline_hash"]
    assert failed["runs"][0]["credits_charged"] == 0


async def test_notifications_only_for_saved_baseline_and_changes_and_delete_clears_links(content_monitor, monkeypatch):
    from internet_hands import dataset_webhook_store
    from internet_hands.dataset_webhook_store import WebhookStore
    from internet_hands.datasets import DatasetStore
    control, owner, monitor, _, capture = content_monitor
    monkeypatch.setenv("INTERNET_HANDS_ENCRYPTION_KEY", "isolated-content-monitor-encryption-material")
    monkeypatch.setattr(dataset_webhook_store, "validate_webhook_url", lambda url: url)
    hooks = WebhookStore(control)
    hooks.configure(owner, "https://example.com/hook", True)
    await check(control, monitor)
    await check(control, monitor)
    capture["text"] = "New price $30."
    await check(control, monitor)
    deliveries = hooks.history(owner)
    assert deliveries["total"] == 2
    current = control.get_monitor(owner, monitor["id"])
    dataset_id, digest = current["baseline_dataset_id"], current["baseline_hash"]
    DatasetStore(control).delete(owner, dataset_id)
    current = control.get_monitor(owner, monitor["id"])
    assert current["baseline_dataset_id"] is None and current["baseline_hash"] == digest
    assert current["runs"][0]["dataset_id"] is None
    assert hooks.history(owner)["total"] == 1
    await check(control, monitor)
    assert control.get_monitor(owner, monitor["id"])["last_status"] == "unchanged"


async def test_failed_synchronous_playground_crawl_releases_actual_wallet(content_monitor, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from internet_hands import playground_api
    control, owner, _, key, capture = content_monitor
    capture["status"] = 403
    monkeypatch.setattr(playground_api, "store", control)
    identity = control.api_key_identity_for_user(owner, key["id"])
    monkeypatch.setattr(playground_api, "_playground_identity", lambda *_: identity)
    monkeypatch.setattr(playground_api, "validate_public_http_url", lambda _: None)
    app = FastAPI()
    app.include_router(playground_api.router)
    with TestClient(app) as client:
        response = client.post("/api/playground/run", json={"operation": "crawl", "url": "https://example.com/pricing", "max_pages": 1})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False and data["summary"]["successful"] == 0 and data["summary"]["failed"] == 1
        assert data["usage"]["credits_charged"] == 0
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT monthly_credits,reserved_credits FROM ih_wallets WHERE user_id=%s", (owner,))
        wallet = cur.fetchone()
        assert wallet["monthly_credits"] == 10000 and wallet["reserved_credits"] == 0
