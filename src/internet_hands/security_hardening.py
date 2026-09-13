from __future__ import annotations

import html

from fastapi import APIRouter, HTTPException, Request

from .auth import sha256_text
from .control_api import _origin, _require_user, store
from .control_store import random_token
from .security_api import (
    _deliver,
    _send_verification,
    security,
    two_factor_confirm,
    two_factor_setup,
)


router = APIRouter()


@router.post("/api/auth/2fa/setup")
def two_factor_setup_protected(request: Request):
    user = _require_user(request)
    status = security.account_security(user["id"])
    if status["totp_enabled"]:
        raise HTTPException(
            status_code=409,
            detail="disable the existing two-factor method before starting a new setup",
        )
    return two_factor_setup(request)


@router.post("/api/auth/2fa/confirm")
async def two_factor_confirm_protected(request: Request):
    user = _require_user(request)
    record = security.totp_record(user["id"])
    if record and record.get("totp_enabled"):
        raise HTTPException(status_code=409, detail="two-factor authentication is already enabled")
    return await two_factor_confirm(request)


@router.post("/api/auth/email-verification/send")
async def resend_verification_limited(request: Request):
    user = _require_user(request)
    current = store.get_user(user["id"])
    if not current:
        raise HTTPException(status_code=404, detail="account not found")
    if current["email_verified"]:
        return {"ok": True, "already_verified": True}
    if not security.email_send_allowed(
        user["id"], "email_verification", min_interval_seconds=60
    ):
        raise HTTPException(status_code=429, detail="wait a minute before requesting another email")
    sent = await _send_verification(request, current)
    return {"ok": True, "sent": sent}


@router.post("/api/auth/password-reset/request")
async def password_reset_request_limited(request: Request):
    body = await request.json()
    email = str(body.get("email") or "").strip().lower()
    user = store.get_user_by_email(email) if email else None
    if user and security.email_send_allowed(
        user["id"], "password_reset", min_interval_seconds=60
    ):
        raw = random_token("ih_reset_")
        store.create_password_reset(user["id"], sha256_text(raw))
        reset_url = f"{_origin(request)}/reset-password?token={raw}"
        await _deliver(
            user_id=user["id"],
            email=user["email"],
            event_type="password_reset",
            subject="Reset your Internet Hands password",
            text=(
                f"Reset your Internet Hands password: {reset_url}\n"
                "This link expires in 30 minutes."
            ),
            body_html=(
                "<p style='color:#a8bbc5'>A password reset was requested for your "
                "Internet Hands account.</p>"
                f"<p><a href='{html.escape(reset_url, quote=True)}' "
                "style='display:inline-block;padding:13px 18px;border-radius:10px;"
                "background:#73e5ef;color:#061014;text-decoration:none;font-weight:800'>"
                "Reset password</a></p>"
                "<p style='color:#8aa0aa'>This link expires in 30 minutes. Ignore this "
                "message if you did not request it.</p>"
            ),
        )
    # Deliberately identical whether the account exists or is currently rate limited.
    return {
        "ok": True,
        "message": "If an account exists for that email, a password-reset link has been sent.",
    }
