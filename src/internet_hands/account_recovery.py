from __future__ import annotations

import html
import os

import httpx
from fastapi import APIRouter, HTTPException, Request

from .auth import hash_password, sha256_text
from .control_api import _origin, store
from .control_store import ControlError, random_token

router = APIRouter()


def _generic_response() -> dict[str, object]:
    return {
        "ok": True,
        "message": "If that account exists, password reset instructions have been sent.",
    }


async def _send_reset_email(*, email: str, reset_url: str) -> bool:
    api_key = os.getenv("RESEND_API_KEY")
    sender = os.getenv("INTERNET_HANDS_EMAIL_FROM")
    if not api_key or not sender:
        return False
    body = {
        "from": sender,
        "to": [email],
        "subject": "Reset your Internet Hands password",
        "html": (
            "<div style='font-family:Inter,Arial,sans-serif;background:#080b0f;color:#eef5f9;"
            "padding:32px'><h2>Reset your Internet Hands password</h2>"
            "<p style='color:#9db0bb'>This link expires in 30 minutes.</p>"
            f"<p><a href='{html.escape(reset_url, quote=True)}' style='color:#73e5ef'>"
            "Reset password</a></p>"
            "<p style='color:#718892'>If you did not request this, ignore this email.</p></div>"
        ),
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
        )
    return response.is_success


@router.post("/api/auth/forgot-password")
async def forgot_password(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return _generic_response()
    email = str(body.get("email") or "").strip().lower()
    if not email:
        return _generic_response()
    try:
        user = store.get_user_by_email(email)
    except ControlError:
        return _generic_response()
    if not user:
        return _generic_response()
    if not (os.getenv("RESEND_API_KEY") and os.getenv("INTERNET_HANDS_EMAIL_FROM")):
        return _generic_response()
    token = random_token("ih_reset_")
    try:
        store.create_password_reset(user["id"], sha256_text(token))
    except ControlError:
        return _generic_response()
    base = os.getenv("INTERNET_HANDS_PUBLIC_URL") or _origin(request)
    reset_url = f"{base.rstrip('/')}/reset-password?token={token}"
    await _send_reset_email(email=email, reset_url=reset_url)
    return _generic_response()


@router.post("/api/auth/reset-password")
async def reset_password(request: Request):
    body = await request.json()
    token = str(body.get("token") or "")
    password = str(body.get("password") or "")
    if not token:
        raise HTTPException(status_code=400, detail="reset token is required")
    try:
        encoded = hash_password(password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    token_hash = sha256_text(token)
    store.ensure_schema()
    user_id: str | None = None
    with store._connect() as conn, conn.cursor() as cur:  # noqa: SLF001
        cur.execute(
            """
            SELECT user_id FROM ih_password_resets
            WHERE token_hash=%s AND used_at IS NULL AND expires_at>now()
            """,
            (token_hash,),
        )
        row = cur.fetchone()
        if row:
            user_id = str(row["user_id"])
    if not user_id or not store.consume_password_reset(token_hash, encoded):
        raise HTTPException(status_code=400, detail="reset link is invalid or expired")
    with store._connect() as conn, conn.cursor() as cur:  # noqa: SLF001
        cur.execute("DELETE FROM ih_sessions WHERE user_id=%s", (user_id,))
        cur.execute("UPDATE ih_oauth_tokens SET revoked_at=now() WHERE user_id=%s", (user_id,))
        conn.commit()
    return {"ok": True, "message": "Password updated. Sign in again on all devices."}
