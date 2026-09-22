from __future__ import annotations

import base64
import hmac
import html
import logging
import os
import secrets
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from urllib.parse import urlencode

import httpx
import qrcode
import qrcode.image.svg
from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, RedirectResponse

from .auth import (
    api_key_prefix,
    generate_api_key,
    hash_password,
    sha256_text,
    verify_password,
)
from .control_api import (
    GITHUB_STATE_COOKIE,
    SESSION_COOKIE,
    _cookie_secure,
    _json_error,
    _origin,
    _require_user,
    _require_verified,
    legacy_store,
    store,
)
from .control_store import ControlError, random_token
from .mailer import MailError, mail_provider, send_mail
from .security_store import SecurityStore
from .supabase_auth import (
    SupabaseAuthError,
    admin_create_user as supabase_admin_create_user,
    admin_update_user as supabase_admin_update_user,
    resend_signup as supabase_resend_signup,
    sign_in as supabase_sign_in,
    sign_up as supabase_sign_up,
    update_password_with_access_token as supabase_update_password,
    user_from_access_token as supabase_user_from_access_token,
    verify_signup_otp as supabase_verify_signup_otp,
)
from .totp import (
    decrypt_secret,
    encrypt_secret,
    encryption_configured,
    generate_recovery_codes,
    generate_totp_secret,
    normalize_recovery_code,
    provisioning_uri,
    verify_totp,
)

router = APIRouter()
security = SecurityStore(store)
TWO_FACTOR_COOKIE = "ih_2fa_challenge"
logger = logging.getLogger(__name__)


def _verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _qr_data_uri(value: str) -> str:
    """Return an offline-scannable SVG QR without sending the TOTP secret elsewhere."""
    image = qrcode.make(value, image_factory=qrcode.image.svg.SvgPathImage)
    output = BytesIO()
    image.save(output)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _mail_shell(title: str, body: str) -> str:
    return f"""<!doctype html><html><body style="margin:0;background:#080b0f;color:#eef5f9;font-family:Inter,Arial,sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#080b0f;padding:32px 12px"><tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:620px;background:#0d1218;border:1px solid #26343b;border-radius:20px;padding:32px">
<tr><td><div style="font-size:13px;letter-spacing:.16em;color:#73e5ef;font-weight:800">INTERNET HANDS</div><h1 style="font-size:26px;margin:22px 0 12px">{html.escape(title)}</h1>{body}<p style="color:#718892;font-size:12px;margin-top:28px">Security messages are sent automatically by Internet Hands. Never share API keys, passwords, TOTP secrets, or recovery codes by email.</p></td></tr></table>
</td></tr></table></body></html>"""


async def _deliver(
    *,
    user_id: str | None,
    email: str,
    event_type: str,
    subject: str,
    text: str,
    body_html: str,
    dedupe_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    try:
        event_id = security.claim_email_event(
            user_id=user_id,
            email=email,
            event_type=event_type,
            dedupe_key=dedupe_key,
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001
        event_id = None
    if dedupe_key and event_id is None:
        return True
    try:
        result = await send_mail(
            to=email,
            subject=subject,
            text=text,
            html=_mail_shell(subject, body_html),
        )
    except MailError as exc:
        if event_id:
            security.finish_email_event(event_id, status="failed", error=str(exc))
        message = str(exc).lower()
        reason = (
            "not_configured"
            if "not configured" in message
            else "provider_auth"
            if "http 401" in message or "http 403" in message
            else "provider_rejected"
            if "http 4" in message or "refused" in message
            else "transport_failed"
        )
        logger.warning(
            "transactional email failed",
            extra={
                "event_type": event_type,
                "mail_provider": mail_provider() or "none",
                "failure_reason": reason,
            },
        )
        return False
    if event_id:
        security.finish_email_event(
            event_id,
            status="sent",
            provider=result.provider,
            message_id=result.message_id,
        )
    return True


async def _send_verification(request: Request, user: dict[str, Any]) -> bool:
    token = random_token("ih_verify_")
    code = _verification_code()
    try:
        security.create_email_verification(
            user_id=user["id"],
            email=user["email"],
            token_hash=sha256_text(token),
            code_hash=sha256_text(code),
        )
    except Exception:
        logger.exception(
            "could not create email-verification challenge", extra={"user_id": user["id"]}
        )
        return False
    verify_url = f"{_origin(request)}/api/auth/verify-email?token={token}"
    safe_url = html.escape(verify_url, quote=True)
    body = (
        "<p style='color:#a8bbc5'>Confirm this email address for your Internet Hands account.</p>"
        f"<div style='font-size:34px;letter-spacing:.18em;font-weight:800;margin:24px 0;color:#73e5ef'>{code}</div>"
        f"<p><a href='{safe_url}' style='display:inline-block;padding:13px 18px;border-radius:10px;background:#73e5ef;color:#061014;text-decoration:none;font-weight:800'>Verify email</a></p>"
        "<p style='color:#8aa0aa'>The code and link expire in 15 minutes.</p>"
    )
    return await _deliver(
        user_id=user["id"],
        email=user["email"],
        event_type="email_verification",
        subject="Verify your Internet Hands email",
        text=f"Your Internet Hands verification code is {code}. Verify: {verify_url}\nThis expires in 15 minutes.",
        body_html=body,
    )


async def _send_verified(user: dict[str, Any]) -> None:
    await _deliver(
        user_id=user["id"],
        email=user["email"],
        event_type="account_verified",
        subject="Your Internet Hands account is verified",
        text="Your Internet Hands email has been verified successfully.",
        body_html="<p style='color:#a8bbc5'>Your email is verified. Your account can now create production API keys and use protected account features.</p>",
        dedupe_key=f"account-verified:{user['id']}:{user['email'].lower()}",
    )


async def _send_login_notice(request: Request, user: dict[str, Any], method: str) -> None:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",", 1)[0].strip() or "unknown"
    agent = (request.headers.get("user-agent") or "unknown")[:240]
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    body = (
        f"<p style='color:#a8bbc5'>A successful sign-in to your account just occurred.</p>"
        f"<p><strong>Method:</strong> {html.escape(method)}<br><strong>Time:</strong> {when}<br>"
        f"<strong>IP:</strong> {html.escape(ip)}<br><strong>Device:</strong> {html.escape(agent)}</p>"
        "<p style='color:#8aa0aa'>If this was not you, change your password, revoke API keys, and enable 2FA.</p>"
    )
    await _deliver(
        user_id=user["id"],
        email=user["email"],
        event_type="login_notice",
        subject="New sign-in to Internet Hands",
        text=f"New Internet Hands sign-in via {method} at {when} from {ip}. If this was not you, secure your account.",
        body_html=body,
    )


async def _send_security_notice(user: dict[str, Any], title: str, message: str, key: str) -> None:
    await _deliver(
        user_id=user["id"],
        email=user["email"],
        event_type=key,
        subject=title,
        text=message,
        body_html=f"<p style='color:#a8bbc5'>{html.escape(message)}</p>",
    )


def _session_response(request: Request, user_id: str, payload: dict[str, Any]) -> JSONResponse:
    raw = random_token("ih_sess_")
    store.create_session(user_id=user_id, token_hash=sha256_text(raw))
    response = JSONResponse(jsonable_encoder(payload))
    response.set_cookie(
        SESSION_COOKIE,
        raw,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        max_age=30 * 86400,
        path="/",
    )
    return response


def _create_2fa_challenge(request: Request, user_id: str) -> JSONResponse:
    raw = random_token("ih_2fa_")
    security.create_login_challenge(user_id=user_id, token_hash=sha256_text(raw))
    response = JSONResponse(
        {
            "two_factor_required": True,
            "message": "Enter your authenticator code or a recovery code.",
        }
    )
    response.set_cookie(
        TWO_FACTOR_COOKIE,
        raw,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        max_age=600,
        path="/",
    )
    return response


def _verify_second_factor(user_id: str, value: str) -> bool:
    record = security.totp_record(user_id)
    if not record or not record.get("totp_enabled") or not record.get("totp_secret_enc"):
        return False
    normalized_recovery = normalize_recovery_code(value)
    if (
        len(normalized_recovery) == 12
        and not value.replace("-", "").isdigit()
        and security.consume_recovery_code(user_id, sha256_text(normalized_recovery))
    ):
        return True
    try:
        secret = decrypt_secret(str(record["totp_secret_enc"]))
    except RuntimeError:
        return False
    counter = verify_totp(secret, value)
    if counter is None:
        return False
    return security.accept_totp_counter(user_id, counter)


@router.post("/api/auth/signup")
async def signup_secure(request: Request):
    body = await request.json()
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    display_name = str(body.get("display_name") or "").strip() or None
    if "@" not in email or len(email) > 320:
        raise HTTPException(status_code=400, detail="valid email required")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="password must contain at least 8 characters")

    redirect_to = f"{_origin(request)}/verify-email?verified=1"
    try:
        auth_result = await supabase_sign_up(
            email=email,
            password=password,
            display_name=display_name,
            redirect_to=redirect_to,
        )
    except SupabaseAuthError as exc:
        status = 429 if exc.status_code == 429 else 400 if exc.status_code < 500 else 503
        raise HTTPException(
            status_code=status,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    auth_user = auth_result.get("user") if isinstance(auth_result, dict) else None
    if not isinstance(auth_user, dict) or not auth_user.get("id"):
        raise HTTPException(status_code=502, detail="Supabase Auth did not create an account")
    if auth_user.get("identities") == []:
        raise HTTPException(
            status_code=409,
            detail={"code": "email_in_use", "message": "an account with this email already exists"},
        )

    user = store.get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=502, detail="Supabase identity bridge did not create the account profile")

    verified = bool(user.get("email_verified"))
    payload = {
        "user": user,
        "verification_required": not verified,
        "verification_sent": not verified,
        "verification_mode": "supabase_link" if not verified else None,
        "next": "/dashboard" if verified else "/verify-email",
    }
    return _session_response(request, user["id"], payload)


@router.post("/api/auth/login")
async def login_secure(request: Request):
    body = await request.json()
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    if not email or not password:
        raise HTTPException(status_code=401, detail={"code": "invalid_credentials", "message": "invalid email or password"})

    current = store.get_user_by_email(email)
    auth_id = store.auth_user_id_for_legacy(str(current["id"])) if current else None
    auth_result: dict[str, Any] | None = None
    primary_error: SupabaseAuthError | None = None

    try:
        auth_result = await supabase_sign_in(email=email, password=password)
    except SupabaseAuthError as exc:
        primary_error = exc

    if auth_result is None:
        message = str(primary_error or "").lower()
        code = (primary_error.code if primary_error else "") or ""
        email_unconfirmed = code == "email_not_confirmed" or "email not confirmed" in message

        if email_unconfirmed and current:
            try:
                sent = await supabase_resend_signup(
                    email=email,
                    redirect_to=f"{_origin(request)}/verify-email?verified=1",
                )
            except SupabaseAuthError:
                sent = False
            return _session_response(
                request,
                current["id"],
                {
                    "user": current,
                    "verification_required": True,
                    "verification_sent": sent,
                    "verification_mode": "supabase_link",
                    "verification_context": "signin",
                    "next": "/verify-email",
                },
            )

        # Once an identity is linked to Supabase, legacy passwords are never
        # accepted again. This prevents an old password from becoming a
        # permanent backdoor after a password change.
        if auth_id:
            raise HTTPException(
                status_code=401,
                detail={"code": "invalid_credentials", "message": "invalid email or password"},
            )

        legacy_user = legacy_store.get_user_by_email(email) if legacy_store else None
        if not legacy_user or not verify_password(password, legacy_user.get("password_hash")):
            raise HTTPException(
                status_code=401,
                detail={"code": "invalid_credentials", "message": "invalid email or password"},
            )

        current = current or store.get_user_by_email(email)
        confirmed = bool(
            (current and current.get("email_verified"))
            or legacy_user.get("email_verified")
        )
        display_name = (
            (current or {}).get("display_name")
            or legacy_user.get("display_name")
        )
        try:
            await supabase_admin_create_user(
                email=email,
                password=password,
                display_name=display_name,
                email_confirm=confirmed,
            )
        except SupabaseAuthError as exc:
            # A concurrent migration may have created the Auth identity first.
            current = store.get_user_by_email(email)
            auth_id = (
                store.auth_user_id_for_legacy(str(current["id"]))
                if current
                else None
            )
            if not auth_id:
                raise HTTPException(
                    status_code=503,
                    detail={"code": "auth_migration_failed", "message": str(exc)},
                ) from exc

        current = store.get_user_by_email(email) or current
        if not current:
            raise HTTPException(status_code=502, detail="migrated account could not be loaded")

        auth_id = store.auth_user_id_for_legacy(str(current["id"]))
        if confirmed:
            try:
                auth_result = await supabase_sign_in(email=email, password=password)
            except SupabaseAuthError as exc:
                raise HTTPException(
                    status_code=503,
                    detail={"code": "auth_migration_failed", "message": str(exc)},
                ) from exc
        else:
            try:
                sent = await supabase_resend_signup(
                    email=email,
                    redirect_to=f"{_origin(request)}/verify-email?verified=1",
                )
            except SupabaseAuthError:
                sent = False
            return _session_response(
                request,
                current["id"],
                {
                    "user": current,
                    "verification_required": True,
                    "verification_sent": sent,
                    "verification_mode": "supabase_link",
                    "verification_context": "signin",
                    "next": "/verify-email",
                },
            )

    current = store.get_user_by_email(email)
    if not current:
        raise HTTPException(status_code=502, detail="authenticated account profile is unavailable")

    auth_user = auth_result.get("user") if isinstance(auth_result, dict) else None
    if isinstance(auth_user, dict) and (
        auth_user.get("email_confirmed_at") or auth_user.get("confirmed_at")
    ) and not current.get("email_verified"):
        security.set_email_verified(current["id"], True)
        current = store.get_user(current["id"]) or current

    sec = security.account_security(current["id"])
    if sec["totp_enabled"]:
        return _create_2fa_challenge(request, current["id"])

    if not current["email_verified"]:
        try:
            sent = await supabase_resend_signup(
                email=email,
                redirect_to=f"{_origin(request)}/verify-email?verified=1",
            )
        except SupabaseAuthError:
            sent = False
        return _session_response(
            request,
            current["id"],
            {
                "user": current,
                "verification_required": True,
                "verification_sent": sent,
                "verification_mode": "supabase_link",
                "verification_context": "signin",
                "next": "/verify-email",
            },
        )

    response = _session_response(
        request,
        current["id"],
        {"user": current, "next": "/dashboard"},
    )
    await _send_login_notice(request, current, "Supabase password")
    return response


@router.post("/api/auth/2fa/challenge")
async def complete_2fa_login(request: Request):
    body = await request.json()
    value = str(body.get("code") or body.get("recovery_code") or "").strip()
    raw = request.cookies.get(TWO_FACTOR_COOKIE, "")
    challenge = security.login_challenge(sha256_text(raw)) if raw else None
    if not challenge or not value:
        raise HTTPException(status_code=401, detail="2FA challenge is missing or expired")
    if not _verify_second_factor(challenge["user_id"], value):
        raise HTTPException(status_code=401, detail="invalid authenticator or recovery code")
    if not security.finish_login_challenge(challenge["id"]):
        raise HTTPException(status_code=401, detail="2FA challenge is no longer valid")
    user = store.get_user(challenge["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="account not found")
    pending_verification = not bool(user["email_verified"])
    sent = await _send_verification(request, user) if pending_verification else None
    response = _session_response(
        request,
        user["id"],
        {
            "user": user,
            "two_factor": True,
            "verification_required": pending_verification,
            "verification_sent": sent,
            "verification_context": "signin" if pending_verification else None,
            "next": "/verify-email" if pending_verification else "/dashboard",
        },
    )
    response.delete_cookie(TWO_FACTOR_COOKIE, path="/")
    if not pending_verification:
        await _send_login_notice(request, user, "password + TOTP")
    return response


@router.get("/api/auth/verification/status")
def verification_status(request: Request):
    user = _require_user(request)
    return security.account_security(user["id"])


@router.post("/api/auth/email-verification/send")
async def resend_verification(request: Request):
    user = _require_user(request)
    current = store.get_user(user["id"])
    if not current:
        raise HTTPException(status_code=404, detail="account not found")
    if current["email_verified"]:
        return {"ok": True, "already_verified": True}
    try:
        sent = await supabase_resend_signup(
            email=current["email"],
            redirect_to=f"{_origin(request)}/verify-email?verified=1",
        )
    except SupabaseAuthError as exc:
        raise HTTPException(
            status_code=429 if exc.status_code == 429 else 503,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return {"ok": True, "sent": sent, "verification_mode": "supabase_link"}


@router.post("/api/auth/email-verification/confirm")
async def confirm_verification_code(request: Request):
    user = _require_user(request)
    body = await request.json()
    code = "".join(ch for ch in str(body.get("code") or "") if ch.isdigit())
    if len(code) != 6:
        raise HTTPException(status_code=400, detail="enter the 6-digit verification code")
    try:
        await supabase_verify_signup_otp(email=user["email"], token=code)
    except SupabaseAuthError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": "verification code is invalid or expired"},
        ) from exc
    security.set_email_verified(user["id"], True)
    current = store.get_user(user["id"])
    if current:
        await _send_verified(current)
    return {"ok": True, "verified": True}


@router.get("/api/auth/verify-email")
async def verify_email_link(token: str = ""):
    # Compatibility for verification links issued before the Supabase cutover.
    if not token:
        return RedirectResponse("/login?verify=missing", status_code=302)
    row = security.consume_email_token(sha256_text(token))
    if not row:
        return RedirectResponse("/login?verify=invalid_or_expired", status_code=302)
    current = store.get_user(row["user_id"])
    if current:
        auth_id = store.auth_user_id_for_legacy(current["id"])
        if auth_id:
            try:
                await supabase_admin_update_user(auth_id, email_confirm=True)
            except SupabaseAuthError:
                return RedirectResponse("/verify-email?sync=failed", status_code=302)
        await _send_verified(current)
    return RedirectResponse("/verify-email?verified=1", status_code=302)


@router.get("/api/auth/2fa/status")
def two_factor_status(request: Request):
    user = _require_user(request)
    status = security.account_security(user["id"])
    return {
        "enabled": bool(status["totp_enabled"]),
        "confirmed_at": status.get("totp_confirmed_at"),
        "available": encryption_configured(),
        "email_verified": bool(status["email_verified"]),
    }


@router.post("/api/auth/2fa/setup")
def two_factor_setup(request: Request):
    user = _require_verified(_require_user(request))
    status = security.account_security(user["id"])
    if not status["email_verified"]:
        raise HTTPException(status_code=403, detail="verify your email before enabling 2FA")
    if not encryption_configured():
        raise HTTPException(status_code=503, detail="2FA encryption key is not configured")
    secret = generate_totp_secret()
    security.put_pending_totp(user["id"], encrypt_secret(secret))
    uri = provisioning_uri(secret, user["email"])
    return {
        "secret": secret,
        "otpauth_uri": uri,
        "qr_data_uri": _qr_data_uri(uri),
        "issuer": "Internet Hands",
        "account": user["email"],
        "message": "Add this account to your authenticator, then confirm with a 6-digit code.",
    }


@router.post("/api/auth/2fa/confirm")
async def two_factor_confirm(request: Request):
    user = _require_verified(_require_user(request))
    body = await request.json()
    code = str(body.get("code") or "")
    record = security.totp_record(user["id"])
    if not record or not record.get("totp_secret_enc"):
        raise HTTPException(status_code=409, detail="start 2FA setup first")
    secret = decrypt_secret(str(record["totp_secret_enc"]))
    counter = verify_totp(secret, code)
    if counter is None:
        raise HTTPException(status_code=400, detail="invalid authenticator code")
    recovery_codes = generate_recovery_codes()
    recovery_hashes = [sha256_text(normalize_recovery_code(value)) for value in recovery_codes]
    security.enable_totp(user["id"], counter, recovery_hashes)
    current = store.get_user(user["id"])
    if current:
        await _send_security_notice(
            current,
            "Two-factor authentication enabled",
            "TOTP two-factor authentication was enabled on your Internet Hands account. Keep your recovery codes somewhere safe.",
            "two_factor_enabled",
        )
    return {
        "ok": True,
        "enabled": True,
        "recovery_codes": recovery_codes,
        "warning": "These recovery codes are shown once. Store them securely.",
    }


@router.post("/api/auth/2fa/disable")
async def two_factor_disable(request: Request):
    user = _require_verified(_require_user(request))
    body = await request.json()
    value = str(body.get("code") or body.get("recovery_code") or "").strip()
    if not value or not _verify_second_factor(user["id"], value):
        raise HTTPException(status_code=401, detail="valid authenticator or recovery code required")
    security.disable_totp(user["id"])
    current = store.get_user(user["id"])
    if current:
        await _send_security_notice(
            current,
            "Two-factor authentication disabled",
            "TOTP two-factor authentication was disabled on your Internet Hands account. If you did not do this, reset your password and revoke your API keys immediately.",
            "two_factor_disabled",
        )
    return {"ok": True, "enabled": False}


@router.post("/api/auth/2fa/recovery/regenerate")
async def regenerate_recovery_codes(request: Request, body: dict[str, Any]):
    user = _require_verified(_require_user(request))
    code = str(body.get("code") or "").strip()
    if not code or not _verify_second_factor(user["id"], code):
        raise HTTPException(status_code=401, detail="valid authenticator code required")
    recovery_codes = generate_recovery_codes()
    security.replace_recovery_codes(
        user["id"],
        [sha256_text(normalize_recovery_code(value)) for value in recovery_codes],
    )
    current = store.get_user(user["id"])
    if current:
        await _send_security_notice(
            current,
            "Recovery codes regenerated",
            "Your two-factor recovery codes were regenerated. All previous recovery codes are now invalid.",
            "two_factor_recovery_regenerated",
        )
    return {"ok": True, "recovery_codes": recovery_codes}


@router.patch("/api/account/profile")
async def update_profile(request: Request):
    user = _require_verified(_require_user(request))
    body = await request.json()
    display_name = " ".join(str(body.get("display_name") or "").split())
    if not display_name or len(display_name) > 80:
        raise HTTPException(status_code=400, detail="display name must be 1 to 80 characters")
    try:
        return {"ok": True, "user": store.update_display_name(user["id"], display_name)}
    except ControlError as exc:
        raise _json_error(exc) from exc


@router.get("/api/account/sessions")
def account_sessions(request: Request):
    user = _require_verified(_require_user(request))
    raw = request.cookies.get(SESSION_COOKIE, "")
    return {
        "sessions": store.list_sessions(user["id"], sha256_text(raw)),
    }


@router.post("/api/account/sessions/{session_id}/revoke")
def revoke_account_session(session_id: str, request: Request):
    user = _require_verified(_require_user(request))
    sessions = store.list_sessions(
        user["id"], sha256_text(request.cookies.get(SESSION_COOKIE, ""))
    )
    selected = next((item for item in sessions if item["id"] == session_id), None)
    if not selected or not store.revoke_session(user["id"], session_id):
        raise HTTPException(status_code=404, detail="session not found")
    response = JSONResponse({"ok": True, "signed_out": bool(selected.get("current"))})
    if selected.get("current"):
        response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.post("/api/account/sessions/revoke-all")
def revoke_all_account_sessions(request: Request):
    user = _require_verified(_require_user(request))
    store.revoke_all_sessions(user["id"])
    response = JSONResponse({"ok": True, "signed_out": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.post("/api/account/password")
async def change_account_password(request: Request):
    user = _require_verified(_require_user(request))
    body = await request.json()
    current_password = str(body.get("current_password") or "")
    new_password = str(body.get("new_password") or "")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="password must contain at least 8 characters")

    auth_id = store.auth_user_id_for_legacy(user["id"])
    if auth_id:
        try:
            signed_in = await supabase_sign_in(email=user["email"], password=current_password)
        except SupabaseAuthError as exc:
            raise HTTPException(status_code=401, detail="current password is incorrect") from exc
        access_token = str(signed_in.get("access_token") or "")
        if not access_token:
            raise HTTPException(status_code=503, detail="Supabase session token was not returned")
        try:
            await supabase_update_password(access_token=access_token, password=new_password)
        except SupabaseAuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        legacy_user = legacy_store.get_user_by_email(user["email"]) if legacy_store else None
        if not legacy_user or not verify_password(current_password, legacy_user.get("password_hash")):
            raise HTTPException(status_code=401, detail="current password is incorrect")
        try:
            await supabase_admin_create_user(
                email=user["email"],
                password=new_password,
                display_name=user.get("display_name"),
                email_confirm=bool(user.get("email_verified")),
            )
        except SupabaseAuthError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    store.clear_password_hash(user["id"])
    store.revoke_all_sessions(user["id"])
    await _send_security_notice(
        user,
        "Your Internet Hands password changed",
        "Your password was changed and all web sessions were signed out. If this was not you, reset your password immediately.",
        "password_changed",
    )
    response = JSONResponse({"ok": True, "signed_out": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/api/auth/github/start")
def github_start_secure(request: Request):
    client_id = os.getenv("GITHUB_CLIENT_ID")
    if not client_id:
        return RedirectResponse("/login?github=config_required", status_code=302)
    state = secrets.token_urlsafe(24)
    redirect_uri = f"{_origin(request)}/api/auth/github/callback"
    url = "https://github.com/login/oauth/authorize?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email",
            "state": state,
        }
    )
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        GITHUB_STATE_COOKIE,
        state,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        max_age=600,
    )
    return response


@router.get("/api/auth/github/callback")
async def github_callback_secure(request: Request, code: str = "", state: str = ""):
    if not code or not state or not hmac.compare_digest(
        state, request.cookies.get(GITHUB_STATE_COOKIE, "")
    ):
        return RedirectResponse("/login?github=invalid_state", status_code=302)
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    if not client_id or not client_secret:
        return RedirectResponse("/login?github=config_required", status_code=302)
    async with httpx.AsyncClient(timeout=20.0) as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={"client_id": client_id, "client_secret": client_secret, "code": code},
        )
        token = token_resp.json().get("access_token") if token_resp.is_success else None
        if not token:
            return RedirectResponse("/login?github=exchange_failed", status_code=302)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        user_resp = await client.get("https://api.github.com/user", headers=headers)
        email_resp = await client.get("https://api.github.com/user/emails", headers=headers)
    if not user_resp.is_success:
        return RedirectResponse("/login?github=profile_failed", status_code=302)
    profile = user_resp.json()
    email = profile.get("email")
    if not email and email_resp.is_success:
        emails = email_resp.json()
        primary = next(
            (item for item in emails if item.get("primary") and item.get("verified")), None
        )
        verified = primary or next((item for item in emails if item.get("verified")), None)
        email = verified.get("email") if verified else None
    if not email:
        return RedirectResponse("/login?github=email_required", status_code=302)

    existing = store.get_user_by_email(str(email))
    user = store.upsert_github_user(
        github_id=str(profile.get("id")),
        email=str(email),
        display_name=profile.get("name") or profile.get("login"),
        avatar_url=profile.get("avatar_url"),
    )
    if existing is None:
        security.set_email_verified(user["id"], False)
    current = store.get_user(user["id"])
    if not current:
        return RedirectResponse("/login?github=account_failed", status_code=302)
    verification_sent = None
    if not current["email_verified"]:
        verification_sent = await _send_verification(request, current)

    sec = security.account_security(user["id"])
    if sec["totp_enabled"]:
        raw = random_token("ih_2fa_")
        security.create_login_challenge(user_id=user["id"], token_hash=sha256_text(raw))
        response = RedirectResponse("/login?two_factor=required&github=1", status_code=302)
        response.set_cookie(
            TWO_FACTOR_COOKIE,
            raw,
            httponly=True,
            secure=_cookie_secure(request),
            samesite="lax",
            max_age=600,
            path="/",
        )
        response.delete_cookie(GITHUB_STATE_COOKIE)
        return response

    raw = random_token("ih_sess_")
    store.create_session(user_id=user["id"], token_hash=sha256_text(raw))
    if current["email_verified"]:
        destination = "/dashboard"
    else:
        destination = "/verify-email?context=signin"
        if verification_sent is False:
            destination += "&delivery=failed"
    response = RedirectResponse(destination, status_code=302)
    response.set_cookie(
        SESSION_COOKIE,
        raw,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        max_age=30 * 86400,
        path="/",
    )
    response.delete_cookie(GITHUB_STATE_COOKIE)
    if current["email_verified"]:
        await _send_login_notice(request, current, "GitHub")
    return response


@router.post("/api/api-keys")
async def create_verified_api_key(request: Request):
    user = _require_user(request)
    status = security.account_security(user["id"])
    if not status["email_verified"]:
        raise HTTPException(status_code=403, detail="verify your email before creating API keys")
    body = await request.json()
    environment = "test" if body.get("environment") == "test" else "live"
    name = str(body.get("name") or "Default key").strip()[:80]
    scopes = body.get("scopes") or [
        "mcp:read",
        "mcp:execute",
        "account:read",
        "monitors:read",
    ]
    if not isinstance(scopes, list) or not all(isinstance(item, str) for item in scopes):
        raise HTTPException(status_code=400, detail="scopes must be a string array")
    raw = generate_api_key(environment)
    try:
        record = store.create_api_key(
            user_id=user["id"],
            name=name,
            prefix=api_key_prefix(raw),
            key_hash=sha256_text(raw),
            scopes=scopes,
            environment=environment,
        )
    except ControlError as exc:
        raise _json_error(exc) from exc
    return {
        "key": record,
        "secret": raw,
        "warning": "This value is shown once. Store it securely.",
    }


@router.post("/api/auth/password-reset/request")
async def password_reset_request_smtp(request: Request):
    body = await request.json()
    email = str(body.get("email") or "").strip().lower()
    user = store.get_user_by_email(email) if email else None
    if user:
        raw = random_token("ih_reset_")
        store.create_password_reset(user["id"], sha256_text(raw))
        reset_url = f"{_origin(request)}/reset-password?token={raw}"
        await _deliver(
            user_id=user["id"],
            email=user["email"],
            event_type="password_reset",
            subject="Reset your Internet Hands password",
            text=f"Reset your Internet Hands password: {reset_url}\nThis link expires in 30 minutes.",
            body_html=(
                "<p style='color:#a8bbc5'>A password reset was requested for your Internet Hands account.</p>"
                f"<p><a href='{html.escape(reset_url, quote=True)}' style='display:inline-block;padding:13px 18px;border-radius:10px;background:#73e5ef;color:#061014;text-decoration:none;font-weight:800'>Reset password</a></p>"
                "<p style='color:#8aa0aa'>This link expires in 30 minutes. Ignore this message if you did not request it.</p>"
            ),
        )
    return {
        "ok": True,
        "message": "If an account exists for that email, a password-reset link has been sent.",
    }


@router.post("/api/auth/password-reset/confirm")
async def password_reset_confirm_secure(request: Request):
    body = await request.json()
    token = str(body.get("token") or "")
    access_token = str(body.get("access_token") or "")
    password = str(body.get("password") or "")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="password must contain at least 8 characters")

    if access_token:
        try:
            auth_user = await supabase_update_password(
                access_token=access_token,
                password=password,
            )
        except SupabaseAuthError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": exc.code, "message": "reset session is invalid or expired"},
            ) from exc
        email = str(auth_user.get("email") or "")
        current = store.get_user_by_email(email) if email else None
        if current:
            store.clear_password_hash(current["id"])
            store.revoke_all_sessions(current["id"])
        return {"ok": True}

    if not token:
        raise HTTPException(status_code=400, detail="reset token is required")

    token_hash = sha256_text(token)
    reset_user = store.password_reset_user(token_hash)
    if not reset_user:
        raise HTTPException(status_code=400, detail="reset token is invalid or expired")

    auth_id = store.auth_user_id_for_legacy(reset_user["id"])
    try:
        if auth_id:
            await supabase_admin_update_user(auth_id, password=password)
        else:
            await supabase_admin_create_user(
                email=reset_user["email"],
                password=password,
                display_name=reset_user.get("display_name"),
                email_confirm=bool(reset_user.get("email_verified")),
            )
    except SupabaseAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Consume the pre-cutover compatibility reset token, then remove the
    # temporary compatibility hash immediately.
    encoded = hash_password(password)
    if not store.consume_password_reset(token_hash, encoded):
        raise HTTPException(status_code=400, detail="reset token is invalid or expired")
    store.clear_password_hash(reset_user["id"])
    store.revoke_all_sessions(reset_user["id"])
    return {"ok": True}


@router.get("/api/security/status")
def security_status(request: Request):
    user = _require_user(request)
    status = security.account_security(user["id"])
    return {
        "email_verified": bool(status["email_verified"]),
        "two_factor_enabled": bool(status["totp_enabled"]),
        "two_factor_available": encryption_configured(),
        "transactional_mail_configured": bool(mail_provider()),
    }
