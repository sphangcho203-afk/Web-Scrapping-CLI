from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from internet_hands.control_store import AuthIdentity, ControlError, ControlStore
from internet_hands.crawl_runs import RunStore


@pytest.fixture
def runs():
    dsn = os.getenv("OPENCRAWL_TEST_DATASET_DSN")
    if not dsn:
        pytest.skip("Requires an isolated PostgreSQL test database.")
    control = ControlStore(dsn)
    control.ensure_schema()
    owner = "runs_" + uuid.uuid4().hex
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO ih_users(id,email) VALUES (%s,%s)", (owner, owner + "@test.invalid"))
        cur.execute("INSERT INTO ih_wallets(user_id,monthly_credits) VALUES (%s,10000)", (owner,))
    identity = AuthIdentity(owner, None, ["mcp:execute"], "free", 100, "session", 10)
    try:
        yield RunStore(control), identity
    finally:
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM ih_users WHERE id=%s", (owner,))


def test_concurrent_create_is_one_reservation_and_conflicting_input_rejected(runs):
    jobs, identity = runs
    args = {"url": "https://example.com", "max_pages": 3}
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: jobs.create(identity, "same", args), range(4)))
    assert len({row["id"] for row in rows}) == 1
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM ih_usage_events WHERE user_id=%s", (identity.user_id,))
        assert cur.fetchone()["n"] == 1
    with pytest.raises(ControlError, match="different"):
        jobs.create(identity, "same", {**args, "max_pages": 4})


def test_recovery_fences_old_worker_and_settles_once(runs):
    jobs, identity = runs
    row = jobs.create(identity, "recover", {"url": "https://example.com"})
    first = jobs.claim()
    assert first["id"] == row["id"]
    assert jobs.claim() is None
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_crawl_runs SET lease_until=now()-interval '1 second' WHERE id=%s", (row["id"],))
    second = jobs.claim()
    assert second["attempts"] == 2 and second["lease_token"] != first["lease_token"]
    output = {"pages": [{"url": "https://example.com", "status_code": 200, "text": "Captured"}]}
    assert jobs.finish(first, "completed", output, {"completed": True}) is False
    assert jobs.finish(second, "completed", output, {"completed": True}) is True
    assert jobs.finish(second, "completed", output, {"completed": True}) is False
    saved = jobs.get(identity.user_id, row["id"])
    assert saved["status"] == "completed" and saved["dataset_id"]
    assert saved["credits_charged"] > 0
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT reserved_credits FROM ih_wallets WHERE user_id=%s", (identity.user_id,))
        assert cur.fetchone()["reserved_credits"] == 0
        cur.execute("SELECT count(*) AS n FROM ih_datasets WHERE user_id=%s", (identity.user_id,))
        assert cur.fetchone()["n"] == 1


def test_all_failed_crawl_is_reported_failed_and_not_charged(runs):
    jobs, identity = runs
    row = jobs.create(identity, "all-failed", {"url": "https://example.com"})
    job = jobs.claim()
    assert jobs.finish(job, "completed", {"pages": [{"url": "https://example.com", "status_code": 403}]}, {})
    saved = jobs.get(identity.user_id, row["id"])
    assert saved["status"] == "failed" and saved["error_code"] == "no_successful_pages"
    assert saved["progress"]["successful"] == 0 and saved["progress"]["failed"] == 1
    assert saved["credits_charged"] == 0
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT reserved_credits FROM ih_wallets WHERE user_id=%s", (identity.user_id,))
        assert cur.fetchone()["reserved_credits"] == 0


def test_queued_cancel_refunds_and_foreign_access_fails(runs):
    jobs, identity = runs
    row = jobs.create(identity, "cancel", {"url": "https://example.com"})
    with pytest.raises(ControlError, match="not found"):
        jobs.cancel("foreign", row["id"])
    with pytest.raises(ControlError, match="not found"):
        jobs.get("foreign", row["id"])
    cancelled = jobs.cancel(identity.user_id, row["id"])
    assert cancelled["status"] == "cancelled" and cancelled["credits_charged"] == 0
    assert jobs.claim() is None
    assert jobs.cancel(identity.user_id, row["id"])["status"] == "cancelled"


def test_stale_reservation_sweeper_keeps_active_jobs(runs):
    jobs, identity = runs
    row = jobs.create(identity, "old", {"url": "https://example.com"})
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_usage_events SET created_at=now()-interval '2 hours' WHERE request_id=%s", (row["request_id"],))
    assert jobs.control.release_stale_reservations(identity.user_id)["reservations_released"] == 0
    assert jobs.cancel(identity.user_id, row["id"])["credits_charged"] == 0


def test_failed_dataset_transaction_rolls_back_billing_then_recovers(runs, monkeypatch):
    from internet_hands.datasets import DatasetStore
    jobs, identity = runs
    row = jobs.create(identity, "rollback", {"url": "https://example.com"})
    job = jobs.claim()
    original = DatasetStore.save

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("simulated process failure after dataset insertion")

    monkeypatch.setattr(DatasetStore, "save", interrupted)
    with pytest.raises(RuntimeError, match="simulated"):
        jobs.finish(job, "completed", {"pages": [{"url": "https://example.com"}]}, {})
    current = jobs.get(identity.user_id, row["id"])
    assert current["status"] == "running" and current["credits_charged"] == 0
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM ih_datasets WHERE user_id=%s", (identity.user_id,))
        assert cur.fetchone()["n"] == 0
        cur.execute("SELECT reserved_credits FROM ih_wallets WHERE user_id=%s", (identity.user_id,))
        assert cur.fetchone()["reserved_credits"] == row["credits_reserved"]
    monkeypatch.setattr(DatasetStore, "save", original)
    assert jobs.finish(job, "completed", {"pages": [{"url": "https://example.com"}]}, {})


def test_exhausted_worker_recovery_preserves_partial_output(runs):
    jobs, identity = runs
    row = jobs.create(identity, "exhaust", {"url": "https://example.com"})
    for _ in range(2):
        job = jobs.claim()
        jobs.checkpoint(job, {"pages": [{"url": "https://example.com", "text": "Partial"}], "truncated": True}, {})
        with jobs.control._connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE ih_crawl_runs SET lease_until=now()-interval '1 second' WHERE id=%s", (row["id"],))
    assert jobs.claim()["recovered_terminal"]
    current = jobs.get(identity.user_id, row["id"])
    assert current["status"] == "failed" and current["error_code"] == "worker_lost"
    assert current["dataset_id"] and current["progress"]["pages"] == 1
    assert jobs.claim() is None


@pytest.mark.parametrize("cancel", [False, True])
async def test_real_worker_checkpoints_and_running_cancellation(runs, monkeypatch, cancel):
    from datetime import UTC, datetime
    from urllib.robotparser import RobotFileParser

    from internet_hands import crawler
    from internet_hands.crawl_run_api import crawl_arguments
    from internet_hands.crawl_run_worker import dispatch_run
    from internet_hands.datasets import DatasetStore
    from internet_hands.models import FetchResult

    jobs, identity = runs
    row = jobs.create(identity, "worker", crawl_arguments({"url": "https://example.com/", "concurrency": 1}))
    calls = []

    async def fetch(url, **kwargs):
        calls.append(url)
        # Cancel while network work is in flight; the next persisted batch observes it.
        if cancel:
            jobs.cancel(identity.user_id, row["id"])
        body = '<p>Public documentation</p><a href="/next">Next</a>'
        return FetchResult(request_url=url, final_url=url, status_code=200, headers={},
            content_type="text/html", content_length=len(body), sha256="a" * 64,
            elapsed_ms=1, captured_at=datetime.now(UTC), body_text=body)

    async def robots(url):
        parser = RobotFileParser()
        parser.parse(["User-agent: *", "Allow: /"])
        return parser

    monkeypatch.setattr(crawler, "fetch_url", fetch)
    monkeypatch.setattr(crawler, "_robots_for", robots)
    monkeypatch.setattr(crawler, "validate_public_http_url", lambda _: None)
    assert (await dispatch_run(jobs))["processed"] == 1
    current = jobs.get(identity.user_id, row["id"])
    assert current["status"] == ("cancelled" if cancel else "completed")
    assert current["progress"]["pages"] == (1 if cancel else 2)
    assert calls == (["https://example.com/"] if cancel else ["https://example.com/", "https://example.com/next"])
    dataset = DatasetStore(jobs.control).get(identity.user_id, current["dataset_id"])
    assert "Public documentation" in dataset["rows"][0]["text"]
    assert dataset["output"]["run_status"] == current["status"]
    assert current["credits_charged"] > 0
    DatasetStore(jobs.control).delete(identity.user_id, current["dataset_id"])
    assert jobs.get(identity.user_id, row["id"])["dataset_id"] is None
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT checkpoint FROM ih_crawl_runs WHERE id=%s", (row["id"],))
        assert "Public documentation" not in str(cur.fetchone())


def test_expired_queue_and_oversized_output_release_reservations(runs):
    jobs, identity = runs
    expired = jobs.create(identity, "expired", {"url": "https://example.com"})
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_crawl_runs SET expires_at=now()-interval '1 second' WHERE id=%s", (expired["id"],))
    assert jobs.claim()["recovered_terminal"]
    current = jobs.get(identity.user_id, expired["id"])
    assert current["error_code"] == "run_expired" and current["credits_charged"] == 0
    oversized = jobs.create(identity, "oversize", {"url": "https://example.com"})
    job = jobs.claim()
    assert jobs.finish(job, "completed", {"pages": [{"text": "x" * 2000001}]}, {})
    current = jobs.get(identity.user_id, oversized["id"])
    assert current["error_code"] == "output_limit_exceeded" and current["dataset_id"] is None
    assert current["credits_charged"] == 0
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT reserved_credits FROM ih_wallets WHERE user_id=%s", (identity.user_id,))
        assert cur.fetchone()["reserved_credits"] == 0


def test_api_auth_validation_idempotency_and_owned_history(runs, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from internet_hands import crawl_run_api, datasets_api, playground_api
    jobs, identity = runs
    reader = AuthIdentity(identity.user_id, None, ["mcp:read"], "free", 100, "api_key", 10)
    foreign = AuthIdentity("foreign", None, ["mcp:read", "mcp:execute"], "free", 100, "api_key", 10)
    identities = {"execute": identity, "read": reader, "foreign": foreign}
    monkeypatch.setattr(crawl_run_api, "runs", jobs)
    monkeypatch.setattr(playground_api, "authenticate_secret", lambda _, secret: identities.get(secret))
    monkeypatch.setattr(datasets_api, "authenticate_secret", lambda _, secret: identities.get(secret))
    monkeypatch.setattr(crawl_run_api, "validate_public_http_url", lambda _: None)
    app = FastAPI()
    app.include_router(crawl_run_api.router)
    client = TestClient(app)
    headers = {"Authorization": "Bearer execute", "Idempotency-Key": "api"}
    body = {"url": "https://example.com", "max_pages": 3}
    assert client.post("/api/crawl-runs", json=body, headers={**headers, "Authorization": "Bearer read"}).status_code == 403
    assert client.post("/api/crawl-runs", json=body, headers={**headers, "Authorization": "Bearer invalid"}).status_code == 401
    assert client.post("/api/crawl-runs", json=body, headers={"Authorization": "Bearer execute"}).status_code == 422
    for invalid in ({**body, "max_pages": True}, {**body, "include_content": "yes"}, {**body, "operation": "research"},
                    {"url": "https://example.com/" + "é" * 2048}):
        assert client.post("/api/crawl-runs", json=invalid, headers=headers).status_code == 422
    created = client.post("/api/crawl-runs", json=body, headers=headers)
    assert created.status_code == 202 and created.headers["cache-control"] == "no-store"
    run_id = created.json()["run"]["id"]
    assert client.post("/api/crawl-runs", json=body, headers=headers).json()["run"]["id"] == run_id
    assert client.post("/api/crawl-runs", json={**body, "max_pages": 4}, headers=headers).status_code == 409
    assert client.get("/api/crawl-runs", headers={"Authorization": "Bearer read"}).json()["total"] == 1
    base = "/api/crawl-runs/" + run_id
    assert client.get(base, headers={"Authorization": "Bearer foreign"}).status_code == 404
    assert client.post(base + "/cancel", headers={"Authorization": "Bearer read"}).status_code == 403
    assert client.post(base + "/cancel", headers={"Authorization": "Bearer foreign"}).status_code == 404
    assert client.post(base + "/cancel", headers=headers).json()["run"]["status"] == "cancelled"


async def test_new_worker_resumes_atomic_frontier_without_recollecting_seed(runs, monkeypatch):
    from datetime import UTC, datetime
    from urllib.robotparser import RobotFileParser

    from internet_hands import crawler
    from internet_hands.crawl_run_api import crawl_arguments
    from internet_hands.crawl_run_worker import dispatch_run
    from internet_hands.datasets import DatasetStore
    from internet_hands.models import FetchResult

    class WorkerCrash(BaseException):
        pass

    jobs, identity = runs
    row = jobs.create(identity, "resume", crawl_arguments({"url": "https://example.com/", "concurrency": 1}))
    calls = []

    async def fetch(url, **kwargs):
        calls.append(url)
        body = '<p>Seed</p><a href="/next">Next</a>' if url.endswith("/") else '<p>Next page</p>'
        return FetchResult(request_url=url, final_url=url, status_code=200, headers={},
            content_type="text/html", content_length=len(body), sha256="a" * 64,
            elapsed_ms=1, captured_at=datetime.now(UTC), body_text=body)

    async def robots(url):
        parser = RobotFileParser()
        parser.parse(["User-agent: *", "Allow: /"])
        return parser

    monkeypatch.setattr(crawler, "fetch_url", fetch)
    monkeypatch.setattr(crawler, "_robots_for", robots)
    monkeypatch.setattr(crawler, "validate_public_http_url", lambda _: None)
    persist = jobs.checkpoint

    def crash_after_commit(*args):
        persist(*args)
        raise WorkerCrash()

    monkeypatch.setattr(jobs, "checkpoint", crash_after_commit)
    with pytest.raises(WorkerCrash):
        await dispatch_run(jobs)
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM ih_crawl_runs WHERE id=%s", (row["id"],))
        checkpoint = cur.fetchone()
        assert len(checkpoint["checkpoint"]["pages"]) == 1
        assert checkpoint["frontier"]["pending"] == [["https://example.com/next", 1]]
        assert checkpoint["measured_usage"]["counters"]["native_web_requests"] == 1
        cur.execute("UPDATE ih_crawl_runs SET lease_until=now()-interval '1 second' WHERE id=%s", (row["id"],))
    # New instances restore exclusively from the database, as a replacement process does.
    recovered = RunStore(ControlStore(jobs.control.dsn))
    assert (await dispatch_run(recovered))["processed"] == 1
    assert calls == ["https://example.com/", "https://example.com/next"]
    current = recovered.get(identity.user_id, row["id"])
    assert current["status"] == "completed" and current["attempts"] == 2
    dataset = DatasetStore(recovered.control).get(identity.user_id, current["dataset_id"])
    assert len(dataset["rows"]) == 2 and "Seed" in dataset["rows"][0]["text"]
    with recovered.control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT measured_usage,frontier FROM ih_crawl_runs WHERE id=%s", (row["id"],))
        terminal = cur.fetchone()
        assert terminal["measured_usage"]["counters"]["native_web_requests"] == 2
        assert terminal["frontier"] == {}
        cur.execute("SELECT count(*) AS n FROM ih_usage_events WHERE user_id=%s", (identity.user_id,))
        assert cur.fetchone()["n"] == 1


async def test_invalid_frontier_is_visible_and_never_restarts_seed(runs, monkeypatch):
    from internet_hands import crawl_run_worker
    from internet_hands.crawl_run_api import crawl_arguments
    jobs, identity = runs
    row = jobs.create(identity, "invalid-frontier", crawl_arguments({"url": "https://example.com/"}))
    job = jobs.claim()
    jobs.checkpoint(job, {"seed_url": "https://example.com/", "pages": []}, {}, {"version": 999})
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_crawl_runs SET lease_until=now()-interval '1 second' WHERE id=%s", (row["id"],))

    async def unexpected(*args, **kwargs):
        pytest.fail("Invalid checkpoint must not start network collection.")

    monkeypatch.setattr(crawl_run_worker, "crawl", unexpected)
    assert (await crawl_run_worker.dispatch_run(jobs))["processed"] == 1
    current = jobs.get(identity.user_id, row["id"])
    assert current["status"] == "failed" and current["error_code"] == "invalid_checkpoint"
    assert current["credits_charged"] == 0
