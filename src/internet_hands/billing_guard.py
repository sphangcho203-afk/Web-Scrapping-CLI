from __future__ import annotations

import hashlib
import hmac
import json

import httpx
from fastapi import APIRouter, HTTPException, Request

from .control_api import _json_error, _razorpay_config, _require_user, store
from .control_store import ControlError

router = APIRouter()


def checkout_signature(secret: str, order_id: str, payment_id: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        f"{order_id}|{payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def payment_matches_order(payment: dict, payment_row: dict) -> bool:
    return (
        str(payment.get("order_id") or "") == str(payment_row.get("order_id") or "")
        and int(payment.get("amount") or 0) == int(payment_row.get("amount_paise") or 0)
        and str(payment.get("currency") or "").upper()
        == str(payment_row.get("currency") or "INR").upper()
    )


@router.post("/api/billing/verify")
async def billing_verify_captured_only(request: Request):
    user = _require_user(request)
    body = await request.json()
    order_id = str(body.get("razorpay_order_id") or "")
    payment_id = str(body.get("razorpay_payment_id") or "")
    signature = str(body.get("razorpay_signature") or "")
    if not order_id or not payment_id or not signature:
        raise HTTPException(status_code=400, detail="incomplete payment verification payload")
    try:
        key_id, key_secret, _ = _razorpay_config()
    except ControlError as exc:
        raise _json_error(exc) from exc
    expected = checkout_signature(key_secret, order_id, payment_id)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=400, detail="invalid payment signature")
    payment_row = store.get_payment_by_order(order_id)
    if not payment_row or payment_row["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="payment order not found")
    async with httpx.AsyncClient(timeout=20.0, auth=(key_id, key_secret)) as client:
        payment_resp = await client.get(f"https://api.razorpay.com/v1/payments/{payment_id}")
    if not payment_resp.is_success:
        raise HTTPException(status_code=502, detail="Razorpay payment lookup failed")
    payment = payment_resp.json()
    if payment.get("status") != "captured":
        raise HTTPException(status_code=409, detail="payment has not been captured by Razorpay")
    if not payment_matches_order(payment, payment_row):
        raise HTTPException(status_code=409, detail="payment details do not match this Internet Hands order")
    result = store.finalize_payment(order_id=order_id, payment_id=payment_id, status="captured")
    return {
        "ok": True,
        "payment": result,
        "wallet": store.wallet_ledger(user["id"], 20)["wallet"],
    }


@router.post("/api/webhooks/razorpay")
async def razorpay_webhook_captured_only(request: Request):
    raw = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    try:
        _, _, webhook_secret = _razorpay_config()
    except ControlError as exc:
        raise _json_error(exc) from exc
    if not webhook_secret:
        raise HTTPException(status_code=503, detail="Razorpay webhook secret is not configured")
    expected = hmac.new(webhook_secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    valid = bool(signature and hmac.compare_digest(signature, expected))
    payload_hash = hashlib.sha256(raw).hexdigest()
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON") from None
    event_type = str(event.get("event") or "unknown")
    payload = event.get("payload") or {}
    payment_entity = (
        ((payload.get("payment") or {}).get("entity") or {})
        if isinstance(payload, dict)
        else {}
    )
    order_entity = (
        ((payload.get("order") or {}).get("entity") or {})
        if isinstance(payload, dict)
        else {}
    )
    event_header = request.headers.get("x-razorpay-event-id", "")
    event_id = str(event_header or payment_entity.get("id") or order_entity.get("id") or payload_hash)
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
    if event_type in {"payment.captured", "order.paid"}:
        order_id = str(payment_entity.get("order_id") or order_entity.get("id") or "")
        payment_id = str(payment_entity.get("id") or "")
        payment_row = store.get_payment_by_order(order_id) if order_id else None
        if (
            payment_row
            and payment_id
            and payment_entity.get("status") == "captured"
            and payment_matches_order(payment_entity, payment_row)
        ):
            store.finalize_payment(
                order_id=order_id,
                payment_id=payment_id,
                status="captured",
            )
    return {"ok": True}
