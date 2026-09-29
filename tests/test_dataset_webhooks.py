from __future__ import annotations

import hashlib
import hmac

import httpx
import pytest

from internet_hands.dataset_webhooks import delivery_headers, send_webhook, validate_webhook_url
from internet_hands.policy import PolicyError, ResolutionSnapshot


def test_signature_covers_timestamp_and_exact_utf8_body():
    body = '{"name":"অসম"}'.encode()
    headers = delivery_headers("wh_secret", "evt_one", body, timestamp=1_790_000_000)
    expected = hmac.new(b"wh_secret", b"1790000000." + body, hashlib.sha256).hexdigest()
    assert headers["X-OpenCrawl-Signature"] == f"t=1790000000,v1={expected}"
    assert headers["X-OpenCrawl-Delivery"] == "evt_one"


@pytest.mark.parametrize("url", ["http://example.com/hook", "https://user:pass@example.com/", "https://example.com/#token",
                                  "https://127.0.0.1/", "https://10.0.0.1/", "https://example.com:8443/", "https://[", "https://example.com/a b"])
def test_unsafe_webhook_targets_rejected(url):
    with pytest.raises(PolicyError):
        validate_webhook_url(url)


async def test_sender_pins_public_ip_keeps_host_sni_and_does_not_follow_redirects(monkeypatch):
    from datetime import UTC, datetime

    from internet_hands import dataset_webhooks

    snapshot = ResolutionSnapshot("https://hooks.example.com/path?key=token", "hooks.example.com", 443,
                                  ("93.184.216.34",), datetime.now(UTC))
    monkeypatch.setattr(dataset_webhooks, "resolve_public_http_url", lambda _: snapshot)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
    client_type = httpx.AsyncClient
    def client(**kwargs):
        return client_type(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(dataset_webhooks.httpx, "AsyncClient", client)
    status = await send_webhook(snapshot.url, b'{"id":"evt_one"}', {"X-OpenCrawl-Delivery": "evt_one"})
    assert status == 302 and len(requests) == 1
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "hooks.example.com"
    assert requests[0].extensions["sni_hostname"] == "hooks.example.com"


async def test_sender_rejects_rebound_private_address_before_network(monkeypatch):
    from datetime import UTC, datetime

    from internet_hands import dataset_webhooks
    snapshot = ResolutionSnapshot("https://hooks.example.com/", "hooks.example.com", 443,
                                  ("127.0.0.1",), datetime.now(UTC))
    monkeypatch.setattr(dataset_webhooks, "resolve_public_http_url", lambda _: snapshot)
    with pytest.raises(PolicyError):
        await send_webhook(snapshot.url, b"{}", {})


@pytest.fixture
def postgres_webhooks(monkeypatch):
    import os
    import uuid

    from internet_hands.control_store import ControlStore
    from internet_hands.dataset_webhook_store import WebhookStore
    from internet_hands.datasets import DatasetStore

    dsn = os.getenv("OPENCRAWL_TEST_DATASET_DSN")
    if not dsn:
        pytest.skip("Set OPENCRAWL_TEST_DATASET_DSN to an isolated PostgreSQL database.")
    monkeypatch.setenv("INTERNET_HANDS_ENCRYPTION_KEY", "isolated-webhook-test-encryption-material")
    control = ControlStore(dsn)
    control.ensure_schema()
    suffix = uuid.uuid4().hex
    owner, foreign = f"wh_owner_{suffix}", f"wh_other_{suffix}"
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO ih_users(id,email) VALUES (%s,%s),(%s,%s)",
                    (owner, f"{owner}@test.invalid", foreign, f"{foreign}@test.invalid"))
    def save_run(request="one"):
        request_id = f"wh_req_{suffix}_{request}"
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO ih_usage_events(id,user_id,request_id,status) VALUES (%s,%s,%s,'ok') "
                        "ON CONFLICT(request_id) DO NOTHING", (request_id, owner, request_id))
        return DatasetStore(control).save(owner, request_id, "crawl", {"pages": [{"text": "অসম", "url": "https://example.com"}]}, "Source")
    yield control, WebhookStore(control), owner, foreign, save_run
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM ih_users WHERE id IN (%s,%s)", (owner, foreign))


def test_transactional_queue_idempotency_privacy_and_rotation(postgres_webhooks):
    import json

    from internet_hands.control_store import ControlError
    from internet_hands.totp import decrypt_secret

    control, hooks, owner, foreign, save = postgres_webhooks
    save("before")
    assert hooks.history(owner)["total"] == 0
    configured = hooks.configure(owner, "https://hooks.example.com/receive", True)
    secret = configured["signing_secret"]
    assert "secret" not in str(hooks.endpoint(owner))
    dataset = save()
    assert save()["id"] == dataset["id"] and hooks.history(owner)["total"] == 1
    assert hooks.history(foreign)["total"] == 0
    event = hooks.history(owner)["deliveries"][0]
    with pytest.raises(ControlError) as denied:
        hooks.retry(foreign, event["id"])
    assert denied.value.status_code == 404
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM ih_dataset_webhook_deliveries WHERE id=%s", (event["id"],))
        stored = cur.fetchone()
        payload = json.loads(stored["body"])
        assert payload["data"]["dataset_id"] == dataset["id"]
        assert "অসম" not in stored["body"] and secret not in stored["body"]
        cur.execute("SELECT secret_enc FROM ih_dataset_webhook_endpoints WHERE user_id=%s", (owner,))
        encrypted = cur.fetchone()["secret_enc"]
        assert encrypted != secret and decrypt_secret(encrypted) == secret
    assert "signing_secret" not in hooks.configure(owner, "https://hooks.example.com/receive", False)
    assert hooks.claim() == []
    assert save("paused") and hooks.history(owner)["total"] == 1
    rotated = hooks.configure(owner, "https://hooks.example.com/receive", True, True)
    assert rotated["signing_secret"] != secret
    assert len(hooks.claim()) == 1
    hooks.delete_endpoint(owner)
    assert hooks.endpoint(owner) is None and hooks.history(owner)["total"] == 0


def test_leases_retry_exhaustion_replay_and_delete(postgres_webhooks):
    from internet_hands.control_store import ControlError
    from internet_hands.datasets import DatasetStore

    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, "https://hooks.example.com/receive", True)
    dataset = save()
    first = hooks.claim()[0]
    assert hooks.claim() == []  # A second dispatcher cannot claim a live lease.
    hooks.finish(first, http_status=503, error="Receiver returned HTTP 503.")
    row = hooks.history(owner)["deliveries"][0]
    assert row["status"] == "retry" and row["attempts"] == 1
    assert hooks.claim() == []  # Backoff prevents an immediate retry.
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_dataset_webhook_deliveries SET next_attempt_at=now()-interval '1 minute' WHERE id=%s", (first["id"],))
    second = hooks.claim()[0]
    assert second["id"] == first["id"] and second["attempts"] == 2
    hooks.finish(first, http_status=200, error=None)  # Stale worker cannot overwrite new lease.
    assert hooks.history(owner)["deliveries"][0]["status"] == "delivering"
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_dataset_webhook_deliveries SET lease_until=now()-interval '1 minute',attempts=5 WHERE id=%s", (first["id"],))
    assert hooks.claim() == []
    assert hooks.history(owner)["deliveries"][0]["status"] == "failed"
    replay = hooks.retry(owner, first["id"])
    assert replay["attempts"] == 0 and replay["id"] == first["id"]
    third = hooks.claim()[0]
    hooks.finish(third, http_status=204, error=None)
    assert hooks.history(owner)["deliveries"][0]["status"] == "delivered"
    with pytest.raises(ControlError) as delivered:
        hooks.retry(owner, first["id"])
    assert delivered.value.status_code == 409
    DatasetStore(control).delete(owner, dataset["id"])
    assert hooks.history(owner)["total"] == 0


@pytest.mark.parametrize("status,expected", [(204, "delivered"), (503, "retry"), (429, "retry"), (302, "failed"), (401, "failed")])
async def test_dispatcher_signs_and_classifies_receiver_outcomes(postgres_webhooks, monkeypatch, status, expected):
    import json

    from internet_hands import dataset_webhooks

    _, hooks, owner, _, save = postgres_webhooks
    secret = hooks.configure(owner, "https://hooks.example.com/receive", True)["signing_secret"]
    save()
    sent = []
    async def receiver(url, body, headers):
        sent.append((body, headers))
        return status
    monkeypatch.setattr(dataset_webhooks, "send_webhook", receiver)
    result = await dataset_webhooks.dispatch_webhooks(hooks)
    assert result["claimed"] == 1
    body, headers = sent[0]
    stamp, digest = headers["X-OpenCrawl-Signature"].split(",")
    expected_digest = hmac.new(secret.encode(), stamp[2:].encode() + b"." + body, hashlib.sha256).hexdigest()
    assert digest == "v1=" + expected_digest
    assert json.loads(body)["id"] == headers["X-OpenCrawl-Delivery"]
    assert hooks.history(owner)["deliveries"][0]["status"] == expected


async def test_dispatch_failure_does_not_leak_receiver_tokens(postgres_webhooks, monkeypatch):
    from internet_hands import dataset_webhooks

    _, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, "https://hooks.example.com/receive?token=private", True)
    save()
    async def receiver(*args):
        raise httpx.ConnectError("https://hooks.example.com/receive?token=private")
    monkeypatch.setattr(dataset_webhooks, "send_webhook", receiver)
    await dataset_webhooks.dispatch_webhooks(hooks)
    row = hooks.history(owner)["deliveries"][0]
    assert row["status"] == "retry" and "private" not in row["last_error"]


def test_queue_failure_rolls_back_dataset_insert(postgres_webhooks, monkeypatch):
    from internet_hands import datasets

    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, "https://hooks.example.com/receive", True)
    def fail(*args):
        raise RuntimeError("outbox write failed")
    monkeypatch.setattr(datasets, "enqueue_dataset_event", fail)
    with pytest.raises(RuntimeError, match="outbox write failed"):
        save()
    assert datasets.DatasetStore(control).list(owner, limit=25, offset=0)["total"] == 0
    assert hooks.history(owner)["total"] == 0


def test_api_settings_scope_retry_and_scheduler_auth(postgres_webhooks, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from internet_hands import dataset_webhook_api, dataset_webhooks, datasets_api
    from internet_hands.control_store import AuthIdentity

    _, hooks, owner, foreign, save = postgres_webhooks
    monkeypatch.setattr(dataset_webhook_api, "webhooks", hooks)
    monkeypatch.setattr(datasets_api, "_require_user", lambda _: {"id": owner})
    app = FastAPI()
    app.include_router(dataset_webhook_api.router)
    client = TestClient(app)
    configured = client.put("/api/dataset-webhook", json={"url": "https://hooks.example.com/receive"})
    assert configured.status_code == 200 and configured.headers["cache-control"] == "no-store"
    secret = configured.json()["signing_secret"]
    assert secret not in client.get("/api/dataset-webhook").text
    for body in ([], {"url": "https://["}, {"url": "http://example.com"}, {"url": "https://example.com", "enabled": "false"}):
        assert client.put("/api/dataset-webhook", json=body).status_code == 422
    assert client.put("/api/dataset-webhook", content="{bad").status_code == 400
    save()
    assert client.get("/api/dataset-webhook/deliveries").json()["total"] == 1
    assert client.get("/api/internal/dataset-webhooks/tick").status_code == 401
    monkeypatch.setenv("CRON_SECRET", "isolated-scheduler-secret")
    async def receiver(*args):
        return 401
    monkeypatch.setattr(dataset_webhooks, "send_webhook", receiver)
    response = client.get("/api/internal/dataset-webhooks/tick", headers={"Authorization": "Bearer isolated-scheduler-secret"})
    assert response.status_code == 200 and response.json()["processed"] == 1
    event_id = hooks.history(owner)["deliveries"][0]["id"]
    read_key = AuthIdentity(owner, "read", ["mcp:read"], "free", 30, "api_key")
    monkeypatch.setattr(datasets_api, "authenticate_secret", lambda *_: read_key)
    headers = {"Authorization": "Bearer read-only"}
    assert client.get("/api/dataset-webhook", headers=headers).status_code == 200
    assert client.delete("/api/dataset-webhook", headers=headers).status_code == 403
    assert client.post(f"/api/dataset-webhook/deliveries/{event_id}/retry", headers=headers).status_code == 403
    monkeypatch.setattr(datasets_api, "_require_user", lambda _: {"id": foreign})
    assert client.get("/api/dataset-webhook/deliveries").json()["total"] == 0
    assert client.post(f"/api/dataset-webhook/deliveries/{event_id}/retry").status_code == 404
    monkeypatch.setattr(datasets_api, "_require_user", lambda _: {"id": owner})
    assert client.post(f"/api/dataset-webhook/deliveries/{event_id}/retry").json()["delivery"]["status"] == "pending"
    assert client.delete("/api/dataset-webhook").json()["deleted"]


def test_concurrent_claims_are_disjoint_and_history_expires(postgres_webhooks):
    from concurrent.futures import ThreadPoolExecutor

    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, "https://hooks.example.com/receive", True)
    for index in range(8):
        save(str(index))
    with ThreadPoolExecutor(max_workers=2) as workers:
        claims = list(workers.map(lambda _: hooks.claim(), range(2)))
    ids = [event["id"] for batch in claims for event in batch]
    assert len(ids) == 8 and len(set(ids)) == 8
    assert all(len(batch) <= 5 for batch in claims)
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_dataset_webhook_deliveries SET created_at=now()-interval '31 days' WHERE user_id=%s", (owner,))
    assert hooks.claim() == [] and hooks.history(owner)["total"] == 0
