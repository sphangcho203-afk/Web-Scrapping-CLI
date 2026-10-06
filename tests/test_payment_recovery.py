"""Recover captured orders without duplicate credit grants or cross-account access."""
import hashlib
import hmac
import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_content_monitors import content_monitor  # noqa: F401 -- isolated PostgreSQL fixture

from internet_hands import control_hardening


@pytest.fixture
def payment_client(request, monkeypatch):
    fixture = request.getfixturevalue("content_monitor")
    control, owner, _monitor, _key, _capture = fixture
    order_id = "order_" + uuid.uuid4().hex
    payment_id = "pay_" + uuid.uuid4().hex
    order = control.create_payment(user_id=owner, order_id=order_id, amount_paise=9900,
        purpose="credits", plan_slug=None, credit_pack_slug="starter-5k", currency="INR",
        metadata={"purchase_mode": "preset_credit_pack", "credits_snapshot": 5000, "price_inr_snapshot": 99})
    payment = {"id": payment_id, "order_id": order_id, "amount": 9900, "currency": "INR", "status": "captured"}
    monkeypatch.setattr(control_hardening, "store", control)
    monkeypatch.setattr(control_hardening, "_require_user", lambda request: {"id": request.headers.get("x-test-owner", owner)})
    monkeypatch.setattr(control_hardening, "_razorpay_config", lambda: ("rzp_live_isolated", "isolated", "hook"))
    monkeypatch.setattr(control_hardening, "_razorpay_secret", lambda name: ("hook", "supabase_vault"))

    async def lookup(*args):
        return payment if payment["status"] == "captured" else None

    async def no_mail(*args):
        pass

    monkeypatch.setattr(control_hardening, "_fetch_razorpay_payment", lookup)
    monkeypatch.setattr(control_hardening, "_captured_payment_for_order", lookup)
    monkeypatch.setattr(control_hardening, "_send_payment_confirmation", no_mail)
    app = FastAPI()
    app.include_router(control_hardening.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, control, owner, order, payment


def webhook(client, payment, event="payment.captured", signed=True):
    payload = json.dumps({"event": event, "payload": {"payment": {"entity": payment}}}).encode()
    signature = hmac.new(b"hook", payload, hashlib.sha256).hexdigest() if signed else "invalid"
    return client.post("/api/webhooks/razorpay", content=payload,
                       headers={"content-type": "application/json", "x-razorpay-signature": signature})


def assert_one_grant(control, owner, order_id):
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT purchased_credits FROM ih_wallets WHERE user_id=%s", (owner,))
        assert cur.fetchone()["purchased_credits"] == 5000
        cur.execute("SELECT count(*) AS n FROM ih_credit_ledger WHERE user_id=%s AND reference_id=%s", (owner, order_id))
        assert cur.fetchone()["n"] == 1


def test_webhook_received_before_fulfillment_failure_can_retry(payment_client, monkeypatch):
    client, control, owner, order, payment = payment_client
    finalize = control.finalize_payment
    attempts = []

    def flaky(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise RuntimeError("isolated transient fulfillment failure")
        return finalize(**kwargs)

    monkeypatch.setattr(control, "finalize_payment", flaky)
    assert webhook(client, payment).status_code == 500
    assert webhook(client, payment).json()["fulfilled"] is True
    assert webhook(client, payment).json()["fulfilled"] is True
    assert_one_grant(control, owner, order["order_id"])
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM ih_webhook_events WHERE event_type='payment.captured' AND signature_valid=true AND status='fulfilled'")
        assert cur.fetchone()


def test_lifecycle_events_and_invalid_signature_cannot_suppress_capture(payment_client):
    client, control, owner, order, payment = payment_client
    assert webhook(client, payment, signed=False).status_code == 400
    assert webhook(client, payment, event="payment.authorized").json()["fulfilled"] is False
    assert webhook(client, payment).json()["fulfilled"] is True
    assert_one_grant(control, owner, order["order_id"])


def test_owner_can_reconcile_existing_payment_once_and_foreign_owner_cannot(payment_client):
    client, control, owner, order, payment = payment_client
    path = "/api/billing/payments/" + order["order_id"] + "/reconcile"
    assert client.post(path, headers={"x-test-owner": "foreign"}).status_code == 404
    assert client.post(path).json()["fulfilled"] is True
    assert client.post(path).json()["fulfilled"] is True
    assert webhook(client, payment).json()["fulfilled"] is True
    assert_one_grant(control, owner, order["order_id"])


def test_reconciliation_and_webhook_never_fulfill_authorized_or_wrong_amount(payment_client):
    client, control, _owner, order, payment = payment_client
    path = "/api/billing/payments/" + order["order_id"] + "/reconcile"
    payment["status"] = "authorized"
    assert client.post(path).json()["fulfilled"] is False
    assert webhook(client, payment).status_code == 503
    payment["status"] = "captured"
    payment["amount"] = 1
    assert client.post(path).status_code == 409
    assert webhook(client, payment).status_code == 409
    assert control.get_payment_by_order(order["order_id"])["status"] == "created"
