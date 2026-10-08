"""Template contracts: safe dynamic data, recoverable actions, and readable content."""
import asyncio
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from internet_hands import email_templates as templates
from internet_hands import monitor_emails


class ParsedEmail(HTMLParser):
    def __init__(self, value):
        super().__init__()
        self.links, self.tags, self.content = [], [], []
        self.feed(value)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == "a":
            self.links.append(dict(attrs)["href"])

    def handle_data(self, data):
        self.content.append(data)


def test_verification_code_and_fallback_preserve_exact_action_and_expiry():
    url = 'https://opencrawl.top/api/auth/verify-email?token=ih_verify_example&source="quoted"'
    rendered = templates.transactional_email("email_verification", "Subject", "private token", templates.verification_body("004216", url))
    parsed = ParsedEmail(rendered)
    assert parsed.links.count(url) == 2
    assert "004216" in parsed.content
    assert "Expires in 15 minutes" in parsed.content
    assert "private token" not in rendered
    assert "color:#090b12;max-height:0" in rendered
    assert "width=device-width" in rendered


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,unsafe", "/relative", "https:///missing-host"])
def test_email_actions_reject_non_web_destinations(url):
    with pytest.raises(ValueError):
        templates.action("Continue", url)


def test_variable_content_cannot_introduce_elements_or_attributes():
    attack = '<img src=x onerror="alert(1)"><script>bad</script>'
    body = templates.login_body(attack, attack, attack, attack) + templates.payment_body(attack, attack, attack, attack)
    value = templates.render_email(attack, body, preheader=attack, category=attack)
    parsed = ParsedEmail(value)
    assert attack in "".join(parsed.content)
    assert all(tag not in {"script", "iframe", "form", "input"} for tag, _ in parsed.tags)
    assert all(not any(key.startswith("on") for key in attrs) for _, attrs in parsed.tags)
    images = [attrs for tag, attrs in parsed.tags if tag == "img"]
    assert len(images) == 1
    assert images[0]["src"] == "https://opencrawl.top/assets/opencrawl-crab.png"


def test_reset_link_fallback_and_notification_destinations():
    url = "https://opencrawl.top/reset-password?token=ih_reset_example"
    reset = ParsedEmail(templates.reset_body(url))
    assert reset.links == [url, url]
    assert "30 minutes" in "".join(reset.content)
    assert ParsedEmail(templates.verified_body()).links == ["https://opencrawl.top/dashboard"]
    assert ParsedEmail(templates.security_body("Changed")).links == ["https://opencrawl.top/dashboard/settings"]
    assert ParsedEmail(templates.payment_body("Plan", "₹250.00", "order_1", "pay_1")).links == ["https://opencrawl.top/dashboard/billing"]


def test_alert_has_semantic_before_after_fields_and_safe_tracker_link():
    attack = '<img src=x onerror="bad">'
    monitor = {"id": 'mon_1&other="bad"', "name": "Weekly\r\nwatch"}
    changes = [{"product_id": "p", "before": {"price": "99", "currency": "INR", "availability": "InStock"}, "after": {"price": "79", "currency": "INR", "availability": "InStock"}}]
    message = monitor_emails.render_change_email(monitor, changes, ["price", "availability"], {"p": attack})
    parsed = ParsedEmail(message["html"])
    assert "Price: INR 99 → INR 79" in message["text"]
    assert "Availability:" not in message["text"]
    assert {"Field", "Before", "After", "Price", "INR 99", "INR 79"} <= set(parsed.content)
    assert attack in parsed.content
    assert len([tag for tag, _ in parsed.tags if tag == "img"]) == 1
    assert all(not any(key.startswith("on") for key in attrs) for _, attrs in parsed.tags)
    assert "\r" not in message["subject"] and "\n" not in message["subject"]
    assert "https://opencrawl.top/dashboard/products?tracker=mon_1%26other%3D%22bad%22" in parsed.links


def test_test_alert_explains_no_change_or_charge_without_a_change_table():
    message = monitor_emails.render_test_email({"id": "mon_1", "name": "Weekly watch"})
    assert "no collection credits were charged" in message["text"]
    assert "no collection credits were charged" in message["html"]
    assert "Your test alert is here." in message["html"]
    assert not any(tag == "thead" for tag, _ in ParsedEmail(message["html"]).tags)


def test_large_alert_preserves_all_plaintext_changes_and_bounds_html_details():
    changes = [
        {"product_id": str(i), "before": {"price": "99", "currency": "INR", "availability": "InStock"},
         "after": {"price": "79", "currency": "INR", "availability": "OutOfStock"}}
        for i in range(64)
    ]
    names = {str(i): f"Offer {i}: " + "<&>" * 100 for i in range(64)}
    message = monitor_emails.render_change_email({"id": "mon_large", "name": "Large watch"}, changes, ["price", "availability"], names)
    assert len(message["html"].encode("utf-8")) < 80_000
    assert message["text"].count("Price: INR 99 → INR 79") == 64
    assert message["text"].count("Availability: InStock → OutOfStock") == 64
    assert "Offer 63:" in message["text"]
    assert "of 64 changed offers. Open your tracker to review the full change history." in message["html"]
    assert "https://opencrawl.top/dashboard/products?tracker=mon_large" in ParsedEmail(message["html"]).links


@pytest.mark.parametrize("event,sender", [("email_verification", "auth"), ("password_reset", "auth"), ("login_notice", "security")])
def test_delivery_retains_plaintext_recipient_sender_and_event_tracking(monkeypatch, event, sender):
    from internet_hands import security_api

    finished = []
    monkeypatch.setattr(security_api, "security", SimpleNamespace(
        claim_email_event=lambda **kwargs: "event_1",
        finish_email_event=lambda event_id, **kwargs: finished.append((event_id, kwargs)),
    ))
    send = AsyncMock(return_value=SimpleNamespace(provider="test", message_id="message_1"))
    monkeypatch.setattr(security_api, "send_mail", send)
    result = asyncio.run(security_api._deliver(
        user_id="user_1", email="sample@example.test", event_type=event,
        subject="Original subject", text="Original plain-text content",
        body_html=templates.paragraph("Email body"), dedupe_key="dedupe_1",
    ))
    assert result is True
    payload = send.call_args.kwargs
    assert payload["to"] == "sample@example.test"
    assert payload["subject"] == "Original subject"
    assert payload["text"] == "Original plain-text content"
    assert payload["sender_key"] == sender
    assert "Email body" in ParsedEmail(payload["html"]).content
    assert "Original plain-text content" not in payload["html"]
    assert finished == [("event_1", {"status": "sent", "provider": "test", "message_id": "message_1"})]


def test_payment_confirmation_remains_deduplicated_with_billing_sender(monkeypatch):
    from internet_hands import control_hardening

    claimed = iter(["event_1", None])
    finished = []
    monkeypatch.setattr(control_hardening, "store", SimpleNamespace(
        get_user=lambda user_id: {"id": user_id, "email": "sample@example.test"},
    ))
    monkeypatch.setattr(control_hardening, "security_store", SimpleNamespace(
        claim_email_event=lambda **kwargs: next(claimed),
        finish_email_event=lambda event_id, **kwargs: finished.append((event_id, kwargs)),
    ))
    send = AsyncMock(return_value=SimpleNamespace(provider="test", message_id="message_1"))
    monkeypatch.setattr(control_hardening, "send_mail", send)
    payment = {"user_id": "user_1", "order_id": "order_1", "payment_id": "pay_1", "amount_paise": 25000, "currency": "INR"}
    asyncio.run(control_hardening._send_payment_confirmation(payment))
    asyncio.run(control_hardening._send_payment_confirmation(payment))
    assert send.await_count == 1
    payload = send.call_args.kwargs
    assert payload["sender_key"] == "billing"
    assert payload["to"] == "sample@example.test"
    assert "Amount: INR 250.00" in payload["text"]
    assert "₹250.00" in ParsedEmail(payload["html"]).content
    assert "https://opencrawl.top/dashboard/billing" in ParsedEmail(payload["html"]).links
    assert finished == [("event_1", {"status": "sent", "provider": "test", "message_id": "message_1"})]
