from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .control_api import (
    _origin,
    _parse_form,
    _safe_redirect_uri,
    oauth_authorize_page,
    oauth_authorize_submit,
)

router = APIRouter()
SCOPES = ["mcp:read", "mcp:execute", "account:read", "monitors:read", "offline_access"]


def _signing_secret() -> bytes:
    raw = os.getenv("INTERNET_HANDS_OAUTH_SIGNING_SECRET") or os.getenv("INTERNET_HANDS_API_KEY")
    if not raw:
        raise HTTPException(status_code=503, detail="OAuth client registration is not configured")
    return raw.encode("utf-8")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _client_id(payload: dict[str, Any]) -> str:
    encoded = _b64url(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = _b64url(hmac.new(_signing_secret(), encoded.encode("ascii"), hashlib.sha256).digest())
    return f"ih_client_{encoded}.{signature}"


def _client_payload(client_id: str) -> dict[str, Any] | None:
    if not client_id.startswith("ih_client_") or "." not in client_id:
        return None
    token = client_id.removeprefix("ih_client_")
    encoded, signature = token.rsplit(".", 1)
    expected = _b64url(hmac.new(_signing_secret(), encoded.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_b64decode(encoded))
    except (ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _validate_registered_client(client_id: str, redirect_uri: str) -> None:
    payload = _client_payload(client_id)
    if not payload:
        raise HTTPException(status_code=400, detail="unregistered OAuth client")
    redirects = payload.get("redirect_uris")
    if not isinstance(redirects, list) or redirect_uri not in redirects:
        raise HTTPException(status_code=400, detail="redirect_uri is not registered for this client")


@router.get("/.well-known/oauth-protected-resource")
def protected_resource_metadata(request: Request) -> dict[str, Any]:
    origin = _origin(request)
    return {
        "resource": f"{origin}/mcp",
        "authorization_servers": [origin],
        "bearer_methods_supported": ["header"],
        "scopes_supported": SCOPES,
    }


@router.get("/.well-known/oauth-authorization-server")
def authorization_server_metadata(request: Request) -> dict[str, Any]:
    origin = _origin(request)
    return {
        "issuer": origin,
        "authorization_endpoint": f"{origin}/oauth/authorize",
        "token_endpoint": f"{origin}/oauth/token",
        "registration_endpoint": f"{origin}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": SCOPES,
        "authorization_response_iss_parameter_supported": True,
    }


@router.post("/oauth/register")
async def oauth_register(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid client metadata") from exc
    redirect_uris = body.get("redirect_uris") if isinstance(body, dict) else None
    if not isinstance(redirect_uris, list) or not redirect_uris or len(redirect_uris) > 10:
        raise HTTPException(status_code=400, detail="redirect_uris must contain 1 to 10 entries")
    redirects = [str(uri) for uri in redirect_uris]
    if any(not _safe_redirect_uri(uri) for uri in redirects):
        raise HTTPException(status_code=400, detail="unsupported redirect_uri")
    if body.get("token_endpoint_auth_method", "none") != "none":
        raise HTTPException(status_code=400, detail="only public PKCE clients are supported")
    response_types = body.get("response_types") or ["code"]
    grant_types = body.get("grant_types") or ["authorization_code", "refresh_token"]
    if response_types != ["code"] and "code" not in response_types:
        raise HTTPException(status_code=400, detail="authorization code response type is required")
    allowed_grants = {"authorization_code", "refresh_token"}
    if any(str(item) not in allowed_grants for item in grant_types):
        raise HTTPException(status_code=400, detail="unsupported grant type")
    payload = {
        "redirect_uris": redirects,
        "client_name": str(body.get("client_name") or "MCP client")[:160],
        "application_type": str(body.get("application_type") or "web")[:32],
        "iat": int(time.time()),
    }
    client_id = _client_id(payload)
    return {
        "client_id": client_id,
        "client_id_issued_at": payload["iat"],
        "client_name": payload["client_name"],
        "redirect_uris": redirects,
        "response_types": ["code"],
        "grant_types": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_method": "none",
    }


@router.get("/oauth/authorize")
def oauth_authorize_checked(
    request: Request,
    client_id: str,
    redirect_uri: str,
    response_type: str = "code",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    state: str = "",
    scope: str = "mcp:read mcp:execute offline_access",
):
    _validate_registered_client(client_id, redirect_uri)
    return oauth_authorize_page(
        request,
        client_id=client_id,
        redirect_uri=redirect_uri,
        response_type=response_type,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        state=state,
        scope=scope,
    )


@router.post("/oauth/authorize")
async def oauth_authorize_submit_checked(request: Request):
    form = _parse_form(await request.body())
    _validate_registered_client(form.get("client_id", ""), form.get("redirect_uri", ""))
    response = await oauth_authorize_submit(request)
    if isinstance(response, RedirectResponse):
        location = response.headers.get("location")
        if location:
            separator = "&" if "?" in location else "?"
            response.headers["location"] = f"{location}{separator}iss={_origin(request)}"
    return response
