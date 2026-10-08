"""Bounded change emails with provider idempotency and explicit delivery evidence."""
from __future__ import annotations

import asyncio
import os
import uuid

import httpx

from .email_templates import action, change_table, note, paragraph, transactional_email
from .mailer import _from_header, _http_header_secret, _mail_settings, mail_provider

MAX_BATCH = 3
MAX_HTML_CHANGE_BYTES = 70_000
MAX_ATTEMPTS = 5
SEND_WINDOW_HOURS = 23  # The provider retains idempotency keys for 24 hours.
TIMEOUT = 5.0
MANAGE_ORIGIN = "https://opencrawl.top"


class AlertMailError(RuntimeError):
    def __init__(self, message: str, *, permanent: bool = False, uncertain: bool = False):
        super().__init__(message)
        self.permanent, self.uncertain = permanent, uncertain


def alert_mail_settings():
    # Preview builds must not send production change alerts or inspect receipts.
    if os.getenv("VERCEL_ENV") == "preview":
        raise AlertMailError("Change emails are disabled on preview deployments.", permanent=True)
    settings = _mail_settings()
    if mail_provider(settings) != "resend" or not _http_header_secret(settings.resend_api_key):
        raise AlertMailError("Change email delivery is temporarily unavailable.")
    return settings


def selected_changes(changes: list[dict], fields: list[str]) -> list[dict]:
    selected = set(fields) | ({"currency"} if "price" in fields else set())
    result = []
    for change in changes[:64]:
        before, after = change.get("before"), change.get("after")
        before = {k: before.get(k) for k in sorted(selected)} if before is not None else None
        after = {k: after.get(k) for k in sorted(selected)} if after is not None else None
        if before != after:
            result.append({"product_id": change["product_id"], "before": before, "after": after})
    return result


def _value(row, field):
    if row is None:
        return "Offer absent"
    if field == "price":
        return (str(row.get("currency") or "") + " " + str(row["price"])).strip() if row.get("price") is not None else "Not published"
    return str(row.get("availability") or "Not published")


def render_change_email(monitor: dict, changes: list[dict], fields: list[str], names: dict) -> dict:
    name = " ".join(str(monitor["name"]).split())[:120]
    lines = ["Selected product fields changed in " + name + "."]
    content = paragraph(lines[0])
    content_bytes = len(content.encode("utf-8"))
    shown, total = 0, 0
    for change in changes:
        product = str(names.get(change["product_id"]) or "Product offer")[:300]
        lines.append("\n" + product)
        rows = []
        for field in fields:
            if _value(change["before"], field) != _value(change["after"], field):
                lines.append(field.title() + ": " + _value(change["before"], field) + " → " + _value(change["after"], field))
                rows.append((field.title(), _value(change["before"], field), _value(change["after"], field)))
        if rows:
            total += 1
            table = change_table(product, rows)
            table_bytes = len(table.encode("utf-8"))
            # Keep the full change list in plain text, but bound the detailed
            # HTML so large batches leave room for the action and footer.
            if shown == total - 1 and content_bytes + table_bytes <= MAX_HTML_CHANGE_BYTES:
                content += table
                content_bytes += table_bytes
                shown += 1
    if shown < total:
        content += paragraph(
            f"Showing {shown} of {total} changed offers. Open your tracker to review the full change history."
        )
    return _message(name, monitor["id"], lines, test=False, content=content)


def render_test_email(monitor: dict) -> dict:
    name = " ".join(str(monitor["name"]).split())[:120]
    return _message(name, monitor["id"], ["This is a test email for " + name + ".",
        "No product change was detected by this test, and no collection credits were charged.",
        "Future change emails show the before and after values of your selected fields."], test=True)


def _message(name, monitor_id, lines, *, test, content=None):
    from urllib.parse import quote
    link = MANAGE_ORIGIN + "/dashboard/products?tracker=" + quote(monitor_id, safe="")
    footer = ["", "Inspect the tracker, change email preferences, or pause tracking: " + link,
              "Emails follow your check schedule. Unchanged checks do not send change emails."]
    text = "\n".join([*lines, *footer])
    subject = ("OpenCrawl test alert: " if test else "OpenCrawl product change: ") + name
    body = (content if content is not None else "".join(paragraph(line) for line in lines))
    body += action("Manage tracker", link) + note(
        "Inspect the tracker, change email preferences, or pause tracking. "
        "Emails follow your check schedule. Unchanged checks do not send change emails."
    )
    return {"subject": subject,
            "text": text, "html": transactional_email("product_test" if test else "product_change", subject, text, body)}


def prepare_payload(event: dict, settings) -> dict:
    if event.get("request_payload"):
        return event["request_payload"]
    payload = {"from": _from_header("resend", settings, "alerts"), "to": [event["recipient"]], **event["message"]}
    if settings.reply_to_email:
        payload["reply_to"] = settings.reply_to_email
    return payload


async def send_alert(event: dict, settings) -> str:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            response = await client.post("https://api.resend.com/emails",
                headers={"Authorization": "Bearer " + _http_header_secret(settings.resend_api_key),
                         "Idempotency-Key": "monitor-alert/" + event["id"]}, json=event["request_payload"])
    except httpx.HTTPError as exc:
        raise AlertMailError("Email send outcome is unknown; a safe retry is scheduled.", uncertain=True) from exc
    if not response.is_success:
        # Do not expose provider bodies, credentials, recipients, or request URLs.
        permanent = 300 <= response.status_code < 500 and response.status_code not in {408, 409, 429}
        raise AlertMailError("Email service returned HTTP " + str(response.status_code) + ".",
                             permanent=permanent, uncertain=response.status_code >= 500 or response.status_code in {408, 409})
    try:
        value = response.json().get("id")
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise AlertMailError("Email was accepted but its confirmation could not be recorded.", uncertain=True) from exc


async def receipt_event(message_id: str, settings) -> str:
    try:
        identifier = str(uuid.UUID(message_id))
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            response = await client.get("https://api.resend.com/emails/" + identifier,
                headers={"Authorization": "Bearer " + _http_header_secret(settings.resend_api_key)})
        if not response.is_success:
            raise AlertMailError("Delivery confirmation is unavailable (HTTP " + str(response.status_code) + ").")
        body = response.json()
        if body.get("id") != identifier or not isinstance(body.get("last_event"), str):
            raise AlertMailError("Delivery confirmation is unavailable.")
        return body["last_event"][:40]
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        raise AlertMailError("Delivery confirmation is temporarily unavailable.") from exc


async def dispatch_monitor_emails(emails, *, event_id: str | None = None) -> dict:
    try:
        settings = await asyncio.to_thread(alert_mail_settings)
    except AlertMailError as exc:
        return {"available": False, "processed": 0, "reason": str(exc)}
    events = await asyncio.to_thread(emails.claim, MAX_BATCH, event_id)
    sent, deferred = 0, 0
    for event in events:
        try:
            payload = prepare_payload(event, settings)
            event = await asyncio.to_thread(emails.begin_attempt, event, payload)
            if not event:
                continue
            message_id = await send_alert(event, settings)
            await asyncio.to_thread(emails.finish, event, message_id=message_id)
            sent += 1
        except AlertMailError as exc:
            await asyncio.to_thread(emails.finish, event, error=str(exc), permanent=exc.permanent, uncertain=exc.uncertain)
        except Exception:  # noqa: BLE001 -- recover the lease; never disclose provider/request data
            # A failed database write after an accepted send is safely retried
            # with the frozen request and its original provider idempotency key.
            deferred += 1
    receipts = await asyncio.to_thread(emails.claim_receipts, MAX_BATCH, event_id)
    confirmed = 0
    for event in receipts:
        try:
            state = await receipt_event(event["provider_id"], settings)
            await asyncio.to_thread(emails.finish_receipt, event, provider_event=state)
            confirmed += state in {"delivered", "opened", "clicked"}
        except AlertMailError as exc:
            await asyncio.to_thread(emails.finish_receipt, event, error=str(exc))
        except Exception:  # noqa: BLE001 -- receipt polling can recover its own lease
            deferred += 1
    return {"available": True, "claimed": len(events), "processed": sent, "receipts_checked": len(receipts), "confirmed": confirmed, "deferred": deferred}
