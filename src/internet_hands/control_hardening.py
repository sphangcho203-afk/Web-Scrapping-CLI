from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request

from .auth import hash_password, sha256_text
from .control_api import _json_error, _origin, _razorpay_config, _require_user, store
from .control_store import ControlError, random_token
from .mailer import MailError, send_mail
from .security_store import SecurityStore

router = APIRouter()
security_store = SecurityStore(store)


async def _fetch_razorpay_payment(
    client: httpx.AsyncClient,
    payment_id: str,
) -> dict[str, Any] | None:
    response = await client.get(f"https://api.razorpay.com/v1/payments/{payment_id}")
    if not response.is_success:
        return None
    payload = response.json()
    return payload if isinstance(payload, dict) else None


async def _captured_payment_for_order(
    client: httpx.AsyncClient,
    order_id: str,
) -> dict[str, Any] | None:
    response = await client.get(f"https://api.razorpay.com/v1/orders/{order_id}/payments")
    if not response.is_success:
        return None
    payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("status") == "captured":
            return item
    return None


def _validate_payment_against_order(payment: dict[str, Any], order: dict[str, Any]) -> None:
    if payment.get("status") != "captured":
        raise HTTPException(status_code=409, detail="payment has not been captured by Razorpay")
    if str(payment.get("order_id") or "") != str(order.get("order_id") or ""):
        raise HTTPException(status_code=409, detail="payment does not belong to this order")
    if int(payment.get("amount") or 0) != int(order.get("amount_paise") or 0):
        raise HTTPException(status_code=409, detail="payment amount does not match the order")
    if str(payment.get("currency") or "").upper() != str(order.get("currency") or "INR").upper():
        raise HTTPException(status_code=409, detail="payment currency does not match the order")


async def _send_payment_confirmation(payment: dict[str, Any]) -> None:
    user = store.get_user(str(payment.get("user_id") or ""))
    if not user:
        return
    order_id = str(payment.get("order_id") or "")
    payment_id = str(payment.get("payment_id") or "")
    dedupe = f"payment-confirmation:{payment_id or order_id}"
    try:
        event_id = security_store.claim_email_event(
            user_id=user["id"],
            email=user["email"],
            event_type="payment_confirmation",
            dedupe_key=dedupe,
            metadata={"order_id": order_id, "payment_id": payment_id},
        )
    except Exception:
        event_id = None
    if event_id is None:
        return
    amount = int(payment.get("amount_paise") or 0) / 100
    purpose = str(payment.get("purpose") or "purchase")
    if purpose == "subscription":
        item = f"Internet Hands {payment.get('plan_slug') or ''} plan"
    else:
        item = f"Internet Hands {payment.get('credit_pack_slug') or 'credit pack'}"
    subject = "Internet Hands payment confirmed"
    text = (
        f"Payment confirmed for {item}. Amount: INR {amount:.2f}. "
        f"Order: {order_id}. Payment: {payment_id}."
    )
    html_body = (
        "<!doctype html><html><body style='font-family:Arial,sans-serif;background:#080b0f;color:#eef5f9;padding:28px'>"
        "<div style='max-width:620px;margin:auto;background:#0d1218;border:1px solid #26343b;border-radius:18px;padding:28px'>"
        "<div style='color:#73e5ef;font-weight:800;letter-spacing:.12em'>INTERNET HANDS</div>"
        "<h2>Payment confirmed</h2>"
        f"<p>Your purchase of <strong>{html.escape(item)}</strong> has been confirmed.</p>"
        f"<p><strong>Amount:</strong> ₹{amount:.2f}<br><strong>Order:</strong> {html.escape(order_id)}<br>"
        f"<strong>Payment:</strong> {html.escape(payment_id)}</p>"
        "<p style='color:#8aa0aa'>Your credits or plan entitlement are already active in the dashboard.</p>"
        "</div></body></html>"
    )
    try:
        result = await send_mail(
            to=user["email"], subject=subject, text=text, html=html_body
        )
    except MailError as exc:
        security_store.finish_email_event(event_id, status="failed", error=str(exc))
        return
    security_store.finish_email_event(
        event_id,
        status="sent",
        provider=result.provider,
        message_id=result.message_id,
    )


@router.post("/api/billing/verify")
async def billing_verify_captured_only(request: Request):
    user = _require_user(request)
    body = await request.json()
    order_id = str(body.get("razorpay_order_id") or "")
    payment_id = str(body.get("razorpay_payment_id") or "")
    signature = str(body.get("razorpay_signature") or "")
    if not order_id or not payment_id or not signature:
        raise HTTPException(status_code=400, detail="missing Razorpay payment verification fields")

    try:
        key_id, key_secret, _ = _razorpay_config()
    except ControlError as exc:
        raise _json_error(exc) from exc

    expected = hmac.new(
        key_secret.encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=400, detail="invalid payment signature")

    order = store.get_payment_by_order(order_id)
    if not order or order["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="payment order not found")

    async with httpx.AsyncClient(timeout=20.0, auth=(key_id, key_secret)) as client:
        payment = await _fetch_razorpay_payment(client, payment_id)
    if not payment:
        raise HTTPException(status_code=502, detail="could not verify payment with Razorpay")

    _validate_payment_against_order(payment, order)
    result = store.finalize_payment(order_id=order_id, payment_id=payment_id, status="captured")
    await _send_payment_confirmation(result)
    return {
        "ok": True,
        "payment": result,
        "wallet": store.wallet_ledger(user["id"], 20)["wallet"],
    }


@router.post("/api/webhooks/razorpay")
async def razorpay_webhook_captured_only(request: Request):
    raw = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    if not webhook_secret:
        raise HTTPException(status_code=503, detail="Razorpay webhook secret is not configured")

    expected = hmac.new(webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
    valid = bool(signature and hmac.compare_digest(signature, expected))
    payload_hash = hashlib.sha256(raw).hexdigest()
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON") from None

    event_type = str(event.get("event") or "unknown")
    payload = event.get("payload") or {}
    payment_entity = ((payload.get("payment") or {}).get("entity") or {}) if isinstance(payload, dict) else {}
    order_entity = ((payload.get("order") or {}).get("entity") or {}) if isinstance(payload, dict) else {}
    event_id = str(event.get("id") or payment_entity.get("id") or order_entity.get("id") or payload_hash)

    inserted = store.record_webhook(
        provider="razorpay",
        event_id=event_id,
        event_type=event_type,
        signature_valid=valid,
        payload_hash=payload_hash,
        status="received" if valid else "rejected",
    )
    if not valid:
        raise HTTPException(status_code=400, detail="invalid webhook signature")
    if not inserted:
        return {"ok": True, "duplicate": True}

    if event_type not in {"payment.captured", "order.paid"}:
        return {"ok": True, "fulfilled": False}

    order_id = str(payment_entity.get("order_id") or order_entity.get("id") or "")
    if not order_id:
        return {"ok": True, "fulfilled": False}
    order = store.get_payment_by_order(order_id)
    if not order:
        return {"ok": True, "fulfilled": False}

    key_id, key_secret, _ = _razorpay_config()
    payment: dict[str, Any] | None = None
    async with httpx.AsyncClient(timeout=20.0, auth=(key_id, key_secret)) as client:
        payment_id = str(payment_entity.get("id") or "")
        if payment_id:
            payment = await _fetch_razorpay_payment(client, payment_id)
        if not payment or payment.get("status") != "captured":
            payment = await _captured_payment_for_order(client, order_id)

    if not payment:
        return {"ok": True, "fulfilled": False, "reason": "no captured payment found"}

    _validate_payment_against_order(payment, order)
    result = store.finalize_payment(
        order_id=order_id,
        payment_id=str(payment["id"]),
        status="captured",
    )
    await _send_payment_confirmation(result)
    return {"ok": True, "fulfilled": True}


async def _send_reset_email(*, email: str, reset_url: str) -> None:
    try:
        await send_mail(
            to=email,
            subject="Reset your Internet Hands password",
            text=f"Reset your Internet Hands password: {reset_url}\nThis link expires in 30 minutes.",
            html=(
                "<p>You requested a password reset for Internet Hands.</p>"
                f"<p><a href=\"{html.escape(reset_url, quote=True)}\">Reset password</a></p>"
                "<p>This link expires in 30 minutes. If you did not request it, ignore this email.</p>"
            ),
        )
    except MailError:
        return


@router.post("/api/auth/password-reset/request")
async def password_reset_request(request: Request):
    body = await request.json()
    email = str(body.get("email") or "").strip().lower()
    user = store.get_user_by_email(email) if email else None
    if user:
        raw = random_token("ih_reset_")
        store.create_password_reset(user["id"], sha256_text(raw))
        reset_url = f"{_origin(request)}/reset-password?token={raw}"
        await _send_reset_email(email=user["email"], reset_url=reset_url)
    return {
        "ok": True,
        "message": "If an account exists for that email, a password-reset link has been sent.",
    }


@router.post("/api/auth/password-reset/confirm")
async def password_reset_confirm(request: Request):
    body = await request.json()
    token = str(body.get("token") or "")
    password = str(body.get("password") or "")
    if not token:
        raise HTTPException(status_code=400, detail="reset token is required")
    try:
        encoded = hash_password(password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not store.consume_password_reset(sha256_text(token), encoded):
        raise HTTPException(status_code=400, detail="reset token is invalid or expired")
    return {"ok": True}
