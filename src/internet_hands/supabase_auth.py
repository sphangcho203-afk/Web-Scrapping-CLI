from __future__ import annotations

import os
from typing import Any

import httpx


class SupabaseAuthError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code or "supabase_auth_error"


def configured() -> bool:
    return bool(
        os.getenv("SUPABASE_URL")
        and os.getenv("SUPABASE_PUBLISHABLE_KEY")
        and os.getenv("SUPABASE_SECRET_KEY")
    )


def _base_url() -> str:
    value = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    if not value:
        raise SupabaseAuthError("Supabase URL is not configured", status_code=503)
    return value


def _publishable_key() -> str:
    value = os.getenv("SUPABASE_PUBLISHABLE_KEY") or ""
    if not value:
        raise SupabaseAuthError("Supabase publishable key is not configured", status_code=503)
    return value


def _secret_key() -> str:
    value = os.getenv("SUPABASE_SECRET_KEY") or ""
    if not value:
        raise SupabaseAuthError("Supabase server key is not configured", status_code=503)
    return value


def _headers(*, secret: bool = False, access_token: str | None = None) -> dict[str, str]:
    api_key = _secret_key() if secret else _publishable_key()
    bearer = access_token or api_key
    return {
        "apikey": api_key,
        "Authorization": f"Bearer {bearer}",
        "Content-Type": "application/json",
    }


def _error_payload(response: httpx.Response) -> tuple[str, str | None]:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        message = str(
            payload.get("msg")
            or payload.get("message")
            or payload.get("error_description")
            or payload.get("error")
            or "Supabase Auth request failed"
        )
        code = payload.get("code") or payload.get("error_code")
        return message, str(code) if code else None
    return "Supabase Auth request failed", None


async def _request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    secret: bool = False,
    access_token: str | None = None,
    expected: tuple[int, ...] = (200,),
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.request(
            method,
            f"{_base_url()}{path}",
            headers=_headers(secret=secret, access_token=access_token),
            json=payload,
            params=params,
        )
    if response.status_code not in expected:
        message, code = _error_payload(response)
        raise SupabaseAuthError(message, status_code=response.status_code, code=code)
    if not response.content:
        return {}
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def sign_up(
    *,
    email: str,
    password: str,
    display_name: str | None = None,
    redirect_to: str | None = None,
) -> dict[str, Any]:
    params = {"redirect_to": redirect_to} if redirect_to else None
    payload: dict[str, Any] = {"email": email, "password": password}
    metadata = {"display_name": display_name} if display_name else {}
    if metadata:
        payload["data"] = metadata
    result = await _request(
        "POST",
        "/auth/v1/signup",
        payload=payload,
        params=params,
        expected=(200, 201),
    )
    # GoTrue returns a bare user object while email confirmation is enabled,
    # and a session-shaped object after immediate confirmation. Normalize both.
    if result.get("id") and result.get("email") and "user" not in result:
        return {"user": result, "session": None}
    return result


async def sign_in(*, email: str, password: str) -> dict[str, Any]:
    return await _request(
        "POST",
        "/auth/v1/token",
        payload={"email": email, "password": password},
        params={"grant_type": "password"},
        expected=(200,),
    )


async def resend_signup(*, email: str, redirect_to: str | None = None) -> bool:
    params = {"redirect_to": redirect_to} if redirect_to else None
    await _request(
        "POST",
        "/auth/v1/resend",
        payload={"type": "signup", "email": email},
        params=params,
        expected=(200,),
    )
    return True


async def verify_signup_otp(*, email: str, token: str) -> dict[str, Any]:
    return await _request(
        "POST",
        "/auth/v1/verify",
        payload={"type": "signup", "email": email, "token": token},
        expected=(200,),
    )


async def request_password_recovery(*, email: str, redirect_to: str | None = None) -> bool:
    params = {"redirect_to": redirect_to} if redirect_to else None
    await _request(
        "POST",
        "/auth/v1/recover",
        payload={"email": email},
        params=params,
        expected=(200,),
    )
    return True


async def user_from_access_token(access_token: str) -> dict[str, Any]:
    return await _request(
        "GET",
        "/auth/v1/user",
        access_token=access_token,
        expected=(200,),
    )


async def update_password_with_access_token(
    *,
    access_token: str,
    password: str,
) -> dict[str, Any]:
    return await _request(
        "PUT",
        "/auth/v1/user",
        payload={"password": password},
        access_token=access_token,
        expected=(200,),
    )


async def admin_create_user(
    *,
    email: str,
    password: str,
    display_name: str | None,
    email_confirm: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "email": email,
        "password": password,
        "email_confirm": email_confirm,
    }
    if display_name:
        payload["user_metadata"] = {"display_name": display_name}
    return await _request(
        "POST",
        "/auth/v1/admin/users",
        payload=payload,
        secret=True,
        expected=(200, 201),
    )


async def admin_update_user(
    auth_user_id: str,
    *,
    password: str | None = None,
    email_confirm: bool | None = None,
    display_name: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if password is not None:
        payload["password"] = password
    if email_confirm is not None:
        payload["email_confirm"] = email_confirm
    if display_name is not None:
        payload["user_metadata"] = {"display_name": display_name}
    if not payload:
        return {}
    return await _request(
        "PUT",
        f"/auth/v1/admin/users/{auth_user_id}",
        payload=payload,
        secret=True,
        expected=(200,),
    )
