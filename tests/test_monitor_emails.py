"""Real outbox/accounting transactions and bounded provider transport fixtures."""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from test_content_monitors import content_monitor, due  # noqa: F401 -- isolated PostgreSQL fixture
from test_payment_recovery import assert_one_grant, payment_client, webhook  # noqa: F401 -- fixture
from test_product_tracker import html, product_monitor, scheduled_check  # noqa: F401 -- fixture

from internet_hands import monitor_email_api, monitor_emails, product_tracker_api
from internet_hands.content_monitors import product_arguments, queue_due_content_checks
from internet_hands.control_store import ControlError
from internet_hands.crawl_run_worker import dispatch_run
from internet_hands.crawl_runs import RunStore
from internet_hands.mailer import MailSettings
from internet_hands.monitor_email_store import MonitorEmailStore
from internet_hands.monitor_emails import AlertMailError, dispatch_monitor_emails


@pytest.fixture
def mail_transport(monkeypatch):
    settings = MailSettings("database", True, "resend", "OpenCrawl", "alerts@example.com", None, {}, "fixture-key")
    requests, accepted = [], {}
    state = {"event": "sent", "status": 200, "timeout": False, "bad_id": False}
    real_client = httpx.AsyncClient

    def handler(request):
        requests.append(request)
        assert request.url.host == "api.resend.com"
        if request.method == "GET":
            identifier = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"id": identifier, "last_event": state["event"]})
        if state["timeout"]:
            raise httpx.ReadTimeout("private request data must not escape", request=request)
        if state["status"] != 200:
            return httpx.Response(state["status"], text="private provider response")
        key = request.headers["Idempotency-Key"]
        body = json.loads(request.content)
        if key in accepted:
            assert accepted[key][0] == body, "Retries must freeze the entire provider request"
        else:
            accepted[key] = (body, str(uuid.uuid4()))
        return httpx.Response(200, json={"id": "invalid" if state["bad_id"] else accepted[key][1]})

    def client(**kwargs):
        assert kwargs["timeout"] == 5 and kwargs["follow_redirects"] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(monitor_emails, "httpx", SimpleNamespace(AsyncClient=client, HTTPError=httpx.HTTPError))
    monkeypatch.setattr(monitor_emails, "alert_mail_settings", lambda: settings)
    monkeypatch.setattr(monitor_email_api, "alert_mail_settings", lambda: settings)
    return settings, requests, state, accepted


@pytest.fixture
def email_monitor(request):
    control, owner, monitor, key, capture = request.getfixturevalue("product_monitor")
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_users SET email_verified=true WHERE id=%s", (owner,))
    return MonitorEmailStore(control), control, owner, monitor, key, capture


def opt_in(emails, owner, monitor, fields=None):
    return emails.configure(owner, monitor["id"], enabled=True, fields=fields or ["price", "availability"], confirm_email=True)


def raw_event(control, identifier):
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM ih_monitor_email_deliveries WHERE id=%s", (identifier,))
        return dict(cur.fetchone())


def expire(control, identifier, *, send=False):
    with control._connect() as conn, conn.cursor() as cur:
        if send:
            cur.execute("UPDATE ih_monitor_email_deliveries SET lease_until=now()-interval '1 minute',next_attempt_at=now() WHERE id=%s", (identifier,))
        else:
            cur.execute("UPDATE ih_monitor_email_deliveries SET next_receipt_at=now(),last_receipt_at=now()-interval '1 minute' WHERE id=%s", (identifier,))


def test_selected_email_fields_and_safe_before_after_rendering():
    change = {"product_id": "p", "before": {"price": "99", "currency": "INR", "availability": "InStock"},
              "after": {"price": "79", "currency": "INR", "availability": "InStock"}}
    assert monitor_emails.selected_changes([change], ["availability"]) == []
    selected = monitor_emails.selected_changes([change], ["price"])
    message = monitor_emails.render_change_email({"id": "mon_test", "name": "Test\r\n<script>"}, selected, ["price"], {"p": "<img onerror=alert(1)>"})
    assert "Price: INR 99 → INR 79" in message["text"]
    assert "Availability:" not in message["text"]
    assert "<script>" not in message["html"] and "<img" not in message["html"]
    assert "\n" not in message["subject"] and "\r" not in message["subject"]
    assert "https://opencrawl.top/dashboard/products?tracker=mon_test" in message["html"]
    added = monitor_emails.selected_changes([{**change, "before": None}], ["price"])
    assert "Offer absent → INR 79" in monitor_emails.render_change_email({"id": "m", "name": "n"}, added, ["price"], {})["text"]


def test_preview_and_non_idempotent_mail_routes_are_unavailable(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "preview")
    with pytest.raises(AlertMailError, match="preview"):
        monitor_emails.alert_mail_settings()
    monkeypatch.delenv("VERCEL_ENV")
    settings = MailSettings("fixture", True, "smtp", "OpenCrawl", "from@example.com", None, {}, None)
    monkeypatch.setattr(monitor_emails, "_mail_settings", lambda: settings)
    with pytest.raises(AlertMailError, match="unavailable"):
        monitor_emails.alert_mail_settings()


async def test_transport_keys_frozen_requests_and_private_errors(mail_transport):
    settings, requests, state, _ = mail_transport
    event = {"id": "mail_fixture", "recipient": "owner@example.com", "message": {"subject": "Test", "text": "Example", "html": "<p>Example</p>"}}
    event["request_payload"] = monitor_emails.prepare_payload(event, settings)
    identifier = await monitor_emails.send_alert(event, settings)
    assert await monitor_emails.send_alert(event, replace(settings, default_from_email="changed@example.com")) == identifier
    assert requests[-1].headers["Idempotency-Key"] == "monitor-alert/mail_fixture"
    assert await monitor_emails.receipt_event(identifier, settings) == "sent"
    assert sum(r.method == "POST" for r in requests) == 2
    state["status"] = 503
    with pytest.raises(AlertMailError) as error:
        await monitor_emails.send_alert(event, settings)
    assert error.value.uncertain and "private" not in str(error.value)
    state["status"], state["bad_id"] = 200, True
    with pytest.raises(AlertMailError) as error:
        await monitor_emails.send_alert(event, settings)
    assert error.value.uncertain
    state["timeout"] = True
    with pytest.raises(AlertMailError) as error:
        await monitor_emails.send_alert(event, settings)
    assert error.value.uncertain and "private" not in str(error.value)
    with pytest.raises(AlertMailError):
        await monitor_emails.receipt_event("https://attacker.example", settings)


async def test_anonymous_settings_actions_and_scheduler_fail_closed(monkeypatch):
    def unexpected():
        pytest.fail("Unauthenticated requests must not consult email credentials")

    monkeypatch.setattr(monitor_email_api, "alert_mail_settings", unexpected)
    app = FastAPI()
    app.include_router(monitor_email_api.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://fixture.invalid") as client:
        assert (await client.get("/api/monitors/mon_private/email-alerts")).status_code == 401
        assert (await client.post("/api/monitors/mon_private/email-alerts/test")).status_code == 401
        assert (await client.get("/api/internal/monitor-emails/tick")).status_code == 401


async def test_existing_purchase_preview_scheduled_change_email_and_failed_credit_release(request, mail_transport, monkeypatch):
    client, control, owner, order, payment = request.getfixturevalue("payment_client")
    _, _, fixture_monitor, key, capture = request.getfixturevalue("product_monitor")
    assert webhook(client, payment).json()["fulfilled"] is True
    assert webhook(client, payment).json()["fulfilled"] is True
    assert_one_grant(control, owner, order["order_id"])
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_users SET email_verified=true WHERE id=%s", (owner,))
        cur.execute("DELETE FROM ih_monitors WHERE id=%s", (fixture_monitor["id"],))
    monkeypatch.setattr(product_tracker_api, "store", control)
    runs = RunStore(control)
    preview = runs.create(control.api_key_identity_for_user(owner, key["id"]), "journey-preview", product_arguments("https://example.com/pricing"))
    await dispatch_run(runs, preview["id"])
    assert product_tracker_api.product_run(owner, preview["id"])["products"][0]["price"] == "99"
    before = control.account_snapshot(owner)["monthly_credits"]
    monitor = product_tracker_api.start_tracking(owner, {"run_id": preview["id"], "name": "Purchased-credit tracker", "confirm_recurring": True})
    assert control.account_snapshot(owner)["monthly_credits"] == before
    emails = MonitorEmailStore(control)
    assert emails.settings(owner, monitor["id"])["preferences"]["enabled"] is False
    opt_in(emails, owner, monitor, ["availability"])
    capture["text"] = html("79")
    await scheduled_check(control, monitor)
    assert emails.history(owner, monitor["id"])["deliveries"] == []
    capture["text"] = html("79", "OutOfStock")
    await scheduled_check(control, monitor)
    queued = emails.history(owner, monitor["id"])["deliveries"]
    assert len(queued) == 1 and queued[0]["status"] == "pending"
    event = raw_event(control, queued[0]["id"])
    assert "Availability: InStock → OutOfStock" in event["message"]["text"]
    assert "Price:" not in event["message"]["text"]
    report = await dispatch_monitor_emails(emails)
    assert report["processed"] == 1 and report["confirmed"] == 0
    accepted = emails.history(owner, monitor["id"])["deliveries"][0]
    assert accepted["status"] == "accepted" and accepted["can_retry"] is False
    mail_transport[2]["event"] = "delivered"
    expire(control, event["id"])
    assert (await dispatch_monitor_emails(emails))["confirmed"] == 1
    assert emails.history(owner, monitor["id"])["deliveries"][0]["status"] == "delivered"
    capture["text"] = html("79", "OutOfStock", extra="Only a banner changed")
    await scheduled_check(control, monitor)
    capture["text"] = "Missing published offer"
    before_failed = control.account_snapshot(owner)["monthly_credits"]
    await scheduled_check(control, monitor)
    final = control.get_monitor(owner, monitor["id"])
    assert final["runs"][0]["status"] == "failed" and final["runs"][0]["credits_charged"] == 0
    assert control.account_snapshot(owner)["monthly_credits"] == before_failed
    assert len(emails.history(owner, monitor["id"])["deliveries"]) == 1
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT reserved_credits,purchased_credits,monthly_credits FROM ih_wallets WHERE user_id=%s", (owner,))
        wallet = cur.fetchone()
        assert wallet["reserved_credits"] == 0 and wallet["purchased_credits"] == 5000
        assert 10000-wallet["monthly_credits"] == runs.get(owner, preview["id"])["credits_charged"]+sum(r["credits_charged"] for r in final["runs"])


async def test_send_recovery_reuses_payload_key_and_never_resends_accepted(email_monitor, mail_transport, monkeypatch):
    emails, control, owner, monitor, _, _ = email_monitor
    opt_in(emails, owner, monitor)
    event = emails.test_email(owner, monitor["id"])
    assert emails.test_email(owner, monitor["id"])["id"] == event["id"]
    finish = emails.finish

    def lost_write(*args, **kwargs):
        raise RuntimeError("commit lost after provider acceptance")

    monkeypatch.setattr(emails, "finish", lost_write)
    assert (await dispatch_monitor_emails(emails, event_id=event["id"]))["deferred"] == 1
    expire(control, event["id"], send=True)
    monkeypatch.setattr(emails, "finish", finish)
    monkeypatch.setattr(monitor_emails, "alert_mail_settings", lambda: replace(mail_transport[0], default_from_email="changed@example.com"))
    assert (await dispatch_monitor_emails(emails, event_id=event["id"]))["processed"] == 1
    assert len(mail_transport[3]) == 1
    assert len([r for r in mail_transport[1] if r.method == "POST"]) == 2
    with pytest.raises(ControlError, match="safely retried"):
        emails.retry(owner, monitor["id"], event["id"])
    await dispatch_monitor_emails(emails, event_id=event["id"])
    assert len([r for r in mail_transport[1] if r.method == "POST"]) == 2
    public = emails.history(owner, monitor["id"])["deliveries"][0]
    assert not {"recipient", "provider_id", "request_payload", "message", "lease_token"}.intersection(public)


async def test_alert_snapshot_and_charge_rollback_together_and_completion_is_idempotent(email_monitor, monkeypatch):
    from internet_hands import monitor_email_store

    emails, control, owner, monitor, _, capture = email_monitor
    opt_in(emails, owner, monitor)
    await scheduled_check(control, monitor)
    before = control.get_monitor(owner, monitor["id"])
    wallet_before = control.account_snapshot(owner)["monthly_credits"]
    enqueue = monitor_email_store.enqueue_change_email

    def unavailable(*args, **kwargs):
        raise RuntimeError("outbox transaction failed")

    monkeypatch.setattr(monitor_email_store, "enqueue_change_email", unavailable)
    capture["text"] = html("79")
    due(control, monitor)
    assert queue_due_content_checks(control)["queued"] == 1
    runs, completion = RunStore(control), []
    finish = runs.finish

    def capture_completion(*args):
        completion.append(args)
        return finish(*args)

    monkeypatch.setattr(runs, "finish", capture_completion)
    with pytest.raises(RuntimeError, match="outbox transaction failed"):
        await dispatch_run(runs)
    after = control.get_monitor(owner, monitor["id"])
    assert after["baseline_dataset_id"] == before["baseline_dataset_id"]
    assert len(after["runs"]) == 1 and control.account_snapshot(owner)["monthly_credits"] == wallet_before
    assert emails.history(owner, monitor["id"])["deliveries"] == []
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM ih_datasets WHERE user_id=%s", (owner,))
        assert cur.fetchone()["n"] == 1
    monkeypatch.setattr(monitor_email_store, "enqueue_change_email", enqueue)
    assert finish(*completion[0]) is True
    assert finish(*completion[0]) is False
    deliveries = emails.history(owner, monitor["id"])["deliveries"]
    assert len(deliveries) == 1 and deliveries[0]["monitor_run_id"]
    assert control.get_monitor(owner, monitor["id"])["baseline_dataset_id"] == deliveries[0]["dataset_id"]


async def test_confirmation_budget_exhaustion_is_visible_without_resending(email_monitor, mail_transport):
    emails, control, owner, monitor, _, _ = email_monitor
    opt_in(emails, owner, monitor)
    event = emails.test_email(owner, monitor["id"])
    await dispatch_monitor_emails(emails, event_id=event["id"])
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_monitor_email_deliveries SET receipt_attempts=24 WHERE id=%s", (event["id"],))
    await dispatch_monitor_emails(emails, event_id=event["id"])
    delivery = emails.history(owner, monitor["id"])["deliveries"][0]
    assert delivery["status"] == "accepted" and not delivery["can_check"]
    assert "unconfirmed" in delivery["receipt_error"]
    assert len([r for r in mail_transport[1] if r.method == "POST"]) == 1


@pytest.mark.parametrize("fence", ["pause", "opt_out", "recipient", "unverify", "edit"])
def test_concurrent_claim_and_last_moment_consent_fences(email_monitor, fence):
    emails, control, owner, monitor, _, _ = email_monitor
    opt_in(emails, owner, monitor)
    event = emails.test_email(owner, monitor["id"])
    with ThreadPoolExecutor(2) as pool:
        claimed = list(pool.map(lambda _: emails.claim(1, event["id"]), range(2)))
    assert sum(map(len, claimed)) == 1
    claimed_event = next(rows[0] for rows in claimed if rows)
    if fence == "pause":
        control.toggle_monitor(owner, monitor["id"], False)
    elif fence == "opt_out":
        emails.configure(owner, monitor["id"], enabled=False, fields=["price"], confirm_email=False)
    else:
        with control._connect() as conn, conn.cursor() as cur:
            if fence == "recipient":
                cur.execute("UPDATE ih_users SET email='changed@test.invalid' WHERE id=%s", (owner,))
            elif fence == "unverify":
                cur.execute("UPDATE ih_users SET email_verified=false WHERE id=%s", (owner,))
            else:
                cur.execute("UPDATE ih_monitors SET content_version=content_version+1 WHERE id=%s", (monitor["id"],))
    assert emails.begin_attempt(claimed_event, {"fixture": True}) is None
    expire(control, event["id"], send=True)
    assert emails.claim(1, event["id"]) == []
    assert raw_event(control, event["id"])["status"] == "cancelled"


async def test_retry_bounds_and_expired_unknown_are_not_resent(email_monitor, mail_transport):
    emails, control, owner, monitor, _, _ = email_monitor
    opt_in(emails, owner, monitor)
    event = emails.test_email(owner, monitor["id"])
    mail_transport[2]["timeout"] = True
    await dispatch_monitor_emails(emails, event_id=event["id"])
    row = raw_event(control, event["id"])
    assert row["status"] == "retry" and row["may_have_sent"]
    assert emails.claim(1, event["id"]) == []  # respects backoff
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_monitor_email_deliveries SET first_dispatch_at=now()-interval '23 hours',next_attempt_at=now() WHERE id=%s", (event["id"],))
    assert emails.claim(1, event["id"]) == []
    assert raw_event(control, event["id"])["status"] == "unknown"
    assert emails.history(owner, monitor["id"])["deliveries"][0]["can_retry"] is False
    with pytest.raises(ControlError):
        emails.retry(owner, monitor["id"], event["id"])
    assert len(mail_transport[1]) == 1


@pytest.mark.parametrize(("provider_event", "expected"), [("sent", "accepted"), ("delivery_delayed", "accepted"), ("delivered", "delivered"), ("opened", "delivered"), ("bounced", "bounced"), ("complained", "complained"), ("failed", "failed")])
async def test_only_provider_delivery_evidence_confirms_receipt(email_monitor, mail_transport, provider_event, expected):
    emails, _, owner, monitor, _, _ = email_monitor
    opt_in(emails, owner, monitor)
    event = emails.test_email(owner, monitor["id"])
    mail_transport[2]["event"] = provider_event
    await dispatch_monitor_emails(emails, event_id=event["id"])
    delivery = emails.history(owner, monitor["id"])["deliveries"][0]
    assert delivery["status"] == expected
    assert bool(delivery["delivered_at"]) == (expected == "delivered")
    assert not delivery["can_retry"]


async def test_owned_api_consent_unavailable_provider_and_preview_do_not_mutate_or_send(email_monitor, mail_transport, monkeypatch):
    emails, _, owner, monitor, _, _ = email_monitor
    monkeypatch.setattr(monitor_email_api, "emails", emails)
    monkeypatch.setattr(monitor_email_api, "_require_user", lambda request: {"id": request.headers.get("x-owner", owner), "email_verified": request.headers.get("x-verified", "true") == "true"})
    app = FastAPI()
    app.include_router(monitor_email_api.router)
    path = "/api/monitors/"+monitor["id"]+"/email-alerts"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://fixture.invalid") as client:
        assert (await client.get(path, headers={"x-owner": "foreign"})).status_code == 404
        body = {"enabled": True, "fields": ["price"], "confirm_email": True}
        assert (await client.put(path, json=body, headers={"x-verified": "false"})).status_code == 403
        assert (await client.put(path, json={**body, "confirm_email": False})).status_code == 422
        assert (await client.put(path, json={**body, "recipient": "attacker@example.com"})).status_code == 422
        assert (await client.put(path, content=b"x"*4001)).status_code == 413
        assert (await client.put(path, json=body)).status_code == 200

        def unavailable():
            raise AlertMailError("Change email delivery is temporarily unavailable.")

        monkeypatch.setattr(monitor_email_api, "alert_mail_settings", unavailable)
        assert (await client.post(path+"/test")).status_code == 503
        assert emails.history(owner, monitor["id"])["deliveries"] == []
        assert (await client.put(path, json={**body, "enabled": False, "confirm_email": False})).status_code == 200
        assert emails.settings(owner, monitor["id"])["preferences"]["enabled"] is False
    assert mail_transport[1] == []
