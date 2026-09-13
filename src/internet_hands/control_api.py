from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import secrets
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .auth import (
    api_key_prefix,
    authenticate_secret,
    generate_api_key,
    hash_password,
    sha256_text,
    verify_password,
    verify_pkce,
)
from .control_store import ControlError, ControlStore, random_token


router = APIRouter()
store = ControlStore()
SESSION_COOKIE = "ih_session"
GITHUB_STATE_COOKIE = "ih_github_state"
DEFAULT_SCOPES = ["mcp:read", "mcp:execute"]


def _json_error(exc: ControlError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.detail})


def _cookie_secure(request: Request) -> bool:
    return (request.headers.get("x-forwarded-proto") or request.url.scheme) == "https"


def _session_user(request: Request) -> dict[str, Any] | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        return store.session_user(sha256_text(raw))
    except ControlError:
        return None


def _require_user(request: Request) -> dict[str, Any]:
    user = _session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "sign in required"})
    return user


def _origin(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".rstrip("/")


def _safe_redirect_uri(uri: str) -> bool:
    try:
        parsed = urlparse(uri)
    except ValueError:
        return False
    if parsed.scheme == "https" and parsed.netloc:
        return True
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}


def _parse_form(raw: bytes) -> dict[str, str]:
    data = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in data.items()}


def _scope_list(value: str | None) -> list[str]:
    scopes = [item.strip() for item in (value or "").split() if item.strip()]
    return scopes or list(DEFAULT_SCOPES)


@router.get("/.well-known/oauth-protected-resource")
def oauth_protected_resource(request: Request) -> dict[str, Any]:
    origin = _origin(request)
    return {
        "resource": f"{origin}/mcp",
        "authorization_servers": [origin],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["mcp:read", "mcp:execute", "account:read", "monitors:read"],
    }


@router.get("/.well-known/oauth-authorization-server")
def oauth_authorization_server(request: Request) -> dict[str, Any]:
    origin = _origin(request)
    return {
        "issuer": origin,
        "authorization_endpoint": f"{origin}/oauth/authorize",
        "token_endpoint": f"{origin}/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["mcp:read", "mcp:execute", "account:read", "monitors:read"],
    }


@router.get("/oauth/authorize", response_class=HTMLResponse)
def oauth_authorize_page(
    request: Request,
    client_id: str,
    redirect_uri: str,
    response_type: str = "code",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    state: str = "",
    scope: str = "mcp:read mcp:execute",
) -> str:
    if response_type != "code" or code_challenge_method != "S256" or not code_challenge:
        raise HTTPException(status_code=400, detail="OAuth authorization code with PKCE S256 is required")
    if not _safe_redirect_uri(redirect_uri):
        raise HTTPException(status_code=400, detail="unsupported redirect_uri")
    signed_in = _session_user(request)
    account_hint = ""
    if signed_in:
        account_hint = f"<div class='account'>Signed in as <strong>{html.escape(str(signed_in['email']))}</strong>. Paste or select an active Internet Hands API key to authorize this client.</div>"
    fields = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": response_type,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "state": state,
        "scope": scope,
    }
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
        for k, v in fields.items()
    )
    scopes = "".join(f"<li>{html.escape(item)}</li>" for item in _scope_list(scope))
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Authorize Internet Hands</title><style>
:root{{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui;background:#080b0f;color:#eef5f9}}*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 20% 0%,#10262b 0,transparent 35%),#080b0f}}.card{{width:min(560px,92vw);padding:32px;border:1px solid #26343b;border-radius:24px;background:#0d1218;box-shadow:0 24px 80px #0008}}.brand{{display:flex;align-items:center;gap:12px;font-weight:800;letter-spacing:.04em}}.mark{{width:34px;height:34px;border-radius:10px;border:1px solid #48d7e8;display:grid;place-items:center;color:#70edf6}}h1{{font-size:26px;margin:26px 0 8px}}p,li{{color:#9db0bb;line-height:1.55}}.client{{padding:14px 16px;background:#101921;border:1px solid #263943;border-radius:14px;margin:20px 0}}input{{width:100%;padding:14px 15px;background:#070a0d;border:1px solid #30414a;border-radius:12px;color:#eef5f9;font:inherit;margin-top:8px}}button{{width:100%;margin-top:18px;padding:14px 16px;border:0;border-radius:12px;background:#73e5ef;color:#061014;font-weight:800;cursor:pointer}}.account{{padding:12px 14px;border-radius:12px;background:#0d1b1f;color:#a8c5cd;margin:14px 0}}small{{color:#718892}}ul{{padding-left:20px}}</style></head><body><main class='card'>
<div class='brand'><div class='mark'>IH</div> INTERNET HANDS</div><h1>Authorize MCP connection</h1><p>A client is requesting access to your Internet Hands capability fabric.</p>
<div class='client'><small>CLIENT ID</small><div>{html.escape(client_id)}</div><small>REDIRECT</small><div style='word-break:break-all'>{html.escape(redirect_uri)}</div></div>{account_hint}
<p>Requested scopes:</p><ul>{scopes}</ul><form method='post'>{hidden}<label>Internet Hands API key<input required autocomplete='off' spellcheck='false' name='api_key' type='password' placeholder='ih_live_…'></label><button type='submit'>Allow connection</button></form><p><small>The raw API key is validated over HTTPS and is never stored by the OAuth session. The client receives a short-lived bearer token instead.</small></p></main></body></html>"""


@router.post("/oauth/authorize")
async def oauth_authorize_submit(request: Request):
    form = _parse_form(await request.body())
    redirect_uri = form.get("redirect_uri", "")
    client_id = form.get("client_id", "")
    code_challenge = form.get("code_challenge", "")
    state = form.get("state", "")
    if not client_id or not code_challenge or not _safe_redirect_uri(redirect_uri):
        raise HTTPException(status_code=400, detail="invalid OAuth request")
    try:
        identity = authenticate_secret(store, form.get("api_key", ""))
    except ControlError as exc:
        raise _json_error(exc) from exc
    if not identity or not identity.api_key_id:
        raise HTTPException(status_code=401, detail="invalid API key")
    requested = _scope_list(form.get("scope"))
    granted = set(identity.scopes or ["*"])
    if "*" not in granted and not set(requested).issubset(granted):
        raise HTTPException(status_code=403, detail="requested scope is not allowed by this API key")
    code = random_token("ih_code_")
    try:
        store.create_oauth_code(
            identity=identity,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_hash=sha256_text(code),
            code_challenge=code_challenge,
            scopes=requested,
        )
    except ControlError as exc:
        raise _json_error(exc) from exc
    query = {"code": code}
    if state:
        query["state"] = state
    separator = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{separator}{urlencode(query)}", status_code=302)


@router.post("/oauth/token")
async def oauth_token(request: Request):
    form = _parse_form(await request.body())
    grant_type = form.get("grant_type")
    client_id = form.get("client_id", "")
    if grant_type == "authorization_code":
        code = form.get("code", "")
        verifier = form.get("code_verifier", "")
        redirect_uri = form.get("redirect_uri", "")
        row = store.consume_oauth_code(sha256_text(code))
        if (
            not row
            or row["client_id"] != client_id
            or row["redirect_uri"] != redirect_uri
            or not verify_pkce(verifier, row["code_challenge"])
        ):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        access = random_token("ih_at_")
        refresh = random_token("ih_rt_")
        scopes = list(row.get("scopes") or [])
        store.create_oauth_token(
            user_id=row["user_id"],
            api_key_id=row["api_key_id"],
            client_id=client_id,
            access_hash=sha256_text(access),
            refresh_hash=sha256_text(refresh),
            scopes=scopes,
        )
        return {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": refresh,
            "scope": " ".join(scopes),
        }
    if grant_type == "refresh_token":
        refresh = form.get("refresh_token", "")
        row = store.consume_refresh_token(sha256_text(refresh), client_id)
        if not row:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        access = random_token("ih_at_")
        new_refresh = random_token("ih_rt_")
        scopes = list(row.get("scopes") or [])
        store.create_oauth_token(
            user_id=row["user_id"],
            api_key_id=row["api_key_id"],
            client_id=client_id,
            access_hash=sha256_text(access),
            refresh_hash=sha256_text(new_refresh),
            scopes=scopes,
        )
        return {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": new_refresh,
            "scope": " ".join(scopes),
        }
    return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)


@router.get("/api/public/plans")
def public_plans():
    try:
        return {"plans": store.list_plans(), "credit_packs": store.list_credit_packs()}
    except ControlError as exc:
        raise _json_error(exc) from exc


@router.post("/api/auth/signup")
async def signup(request: Request):
    body = await request.json()
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    display_name = str(body.get("display_name") or "").strip() or None
    if "@" not in email or len(email) > 320:
        raise HTTPException(status_code=400, detail="valid email required")
    try:
        encoded = hash_password(password)
        user = store.create_user(email=email, password_hash=encoded, display_name=display_name)
        raw = random_token("ih_sess_")
        store.create_session(user_id=user["id"], token_hash=sha256_text(raw))
    except (ValueError, ControlError) as exc:
        if isinstance(exc, ControlError):
            raise _json_error(exc) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = JSONResponse({"user": user})
    response.set_cookie(
        SESSION_COOKIE, raw, httponly=True, secure=_cookie_secure(request), samesite="lax", max_age=30 * 86400, path="/"
    )
    return response


@router.post("/api/auth/login")
async def login(request: Request):
    body = await request.json()
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    user = store.get_user_by_email(email)
    if not user or not verify_password(password, user.get("password_hash")):
        raise HTTPException(status_code=401, detail={"code": "invalid_credentials", "message": "invalid email or password"})
    raw = random_token("ih_sess_")
    store.create_session(user_id=user["id"], token_hash=sha256_text(raw))
    response = JSONResponse({"user": store.get_user(user["id"])})
    response.set_cookie(
        SESSION_COOKIE, raw, httponly=True, secure=_cookie_secure(request), samesite="lax", max_age=30 * 86400, path="/"
    )
    return response


@router.post("/api/auth/logout")
def logout(request: Request):
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        try:
            store.delete_session(sha256_text(raw))
        except ControlError:
            pass
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/api/auth/me")
def auth_me(request: Request):
    user = _require_user(request)
    return {"user": user, "account": store.account_snapshot(user["id"])}


@router.get("/api/auth/github/start")
def github_start(request: Request):
    client_id = os.getenv("GITHUB_CLIENT_ID")
    if not client_id:
        return RedirectResponse("/login?github=config_required", status_code=302)
    state = secrets.token_urlsafe(24)
    redirect_uri = f"{_origin(request)}/api/auth/github/callback"
    url = "https://github.com/login/oauth/authorize?" + urlencode(
        {"client_id": client_id, "redirect_uri": redirect_uri, "scope": "read:user user:email", "state": state}
    )
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(GITHUB_STATE_COOKIE, state, httponly=True, secure=_cookie_secure(request), samesite="lax", max_age=600)
    return response


@router.get("/api/auth/github/callback")
async def github_callback(request: Request, code: str = "", state: str = ""):
    if not code or not state or not hmac.compare_digest(state, request.cookies.get(GITHUB_STATE_COOKIE, "")):
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
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        user_resp = await client.get("https://api.github.com/user", headers=headers)
        email_resp = await client.get("https://api.github.com/user/emails", headers=headers)
    if not user_resp.is_success:
        return RedirectResponse("/login?github=profile_failed", status_code=302)
    profile = user_resp.json()
    email = profile.get("email")
    if not email and email_resp.is_success:
        emails = email_resp.json()
        primary = next((item for item in emails if item.get("primary") and item.get("verified")), None)
        verified = primary or next((item for item in emails if item.get("verified")), None)
        email = verified.get("email") if verified else None
    if not email:
        return RedirectResponse("/login?github=email_required", status_code=302)
    user = store.upsert_github_user(
        github_id=str(profile.get("id")),
        email=str(email),
        display_name=profile.get("name") or profile.get("login"),
        avatar_url=profile.get("avatar_url"),
    )
    raw = random_token("ih_sess_")
    store.create_session(user_id=user["id"], token_hash=sha256_text(raw))
    response = RedirectResponse("/dashboard", status_code=302)
    response.set_cookie(SESSION_COOKIE, raw, httponly=True, secure=_cookie_secure(request), samesite="lax", max_age=30 * 86400, path="/")
    response.delete_cookie(GITHUB_STATE_COOKIE)
    return response


@router.get("/api/api-keys")
def api_keys(request: Request):
    user = _require_user(request)
    return {"keys": store.list_api_keys(user["id"])}


@router.post("/api/api-keys")
async def create_api_key_endpoint(request: Request):
    user = _require_user(request)
    body = await request.json()
    environment = "test" if body.get("environment") == "test" else "live"
    name = str(body.get("name") or "Default key").strip()[:80]
    scopes = body.get("scopes") or ["mcp:read", "mcp:execute", "account:read", "monitors:read"]
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
    return {"key": record, "secret": raw, "warning": "This value is shown once. Store it securely."}


@router.post("/api/api-keys/{key_id}/revoke")
def revoke_api_key_endpoint(key_id: str, request: Request):
    user = _require_user(request)
    if not store.revoke_api_key(user["id"], key_id):
        raise HTTPException(status_code=404, detail="API key not found")
    return {"ok": True}


@router.get("/api/dashboard")
def dashboard(request: Request):
    user = _require_user(request)
    return store.usage_summary(user["id"])


@router.get("/api/usage")
def usage(request: Request, limit: int = 100):
    user = _require_user(request)
    return {"events": store.recent_usage(user["id"], limit)}


@router.get("/api/wallet")
def wallet(request: Request, limit: int = 100):
    user = _require_user(request)
    return store.wallet_ledger(user["id"], limit)


@router.get("/api/monitors")
def monitors(request: Request):
    user = _require_user(request)
    return {"monitors": store.list_monitors(user["id"])}


@router.get("/api/monitors/{monitor_id}")
def monitor(request: Request, monitor_id: str):
    user = _require_user(request)
    row = store.get_monitor(user["id"], monitor_id)
    if not row:
        raise HTTPException(status_code=404, detail="monitor not found")
    return row


@router.post("/api/monitors")
async def create_monitor(request: Request):
    user = _require_user(request)
    body = await request.json()
    monitor_type = str(body.get("type") or "web")
    if monitor_type not in {"web", "api", "mcp", "gaming"}:
        raise HTTPException(status_code=400, detail="invalid monitor type")
    interval = max(5, min(int(body.get("interval_minutes") or 60), 10080))
    try:
        return store.create_monitor(
            user_id=user["id"],
            name=str(body.get("name") or "Monitor")[:120],
            monitor_type=monitor_type,
            target=str(body.get("target") or "")[:2000],
            interval_minutes=interval,
            config=body.get("config") if isinstance(body.get("config"), dict) else {},
        )
    except ControlError as exc:
        raise _json_error(exc) from exc


@router.post("/api/monitors/{monitor_id}/toggle")
async def toggle_monitor(request: Request, monitor_id: str):
    user = _require_user(request)
    body = await request.json()
    enabled = bool(body.get("enabled"))
    if not store.toggle_monitor(user["id"], monitor_id, enabled):
        raise HTTPException(status_code=404, detail="monitor not found")
    return {"ok": True, "enabled": enabled}


def _razorpay_config() -> tuple[str, str, str | None]:
    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    if not key_id or not key_secret:
        raise ControlError("billing_not_configured", "Razorpay billing is not configured", 503)
    return key_id, key_secret, webhook_secret


@router.get("/api/billing/status")
def billing_status(request: Request):
    _require_user(request)
    return {
        "provider": "razorpay",
        "configured": bool(os.getenv("RAZORPAY_KEY_ID") and os.getenv("RAZORPAY_KEY_SECRET")),
        "webhook_configured": bool(os.getenv("RAZORPAY_WEBHOOK_SECRET")),
        "key_id": os.getenv("RAZORPAY_KEY_ID") if os.getenv("RAZORPAY_KEY_ID") else None,
    }


@router.get("/api/billing/payments")
def billing_payments(request: Request):
    user = _require_user(request)
    return {"payments": store.list_payments(user["id"])}


@router.post("/api/billing/create-order")
async def billing_create_order(request: Request):
    user = _require_user(request)
    body = await request.json()
    purpose = str(body.get("purpose") or "credits")
    slug = str(body.get("slug") or "")
    if purpose == "credits":
        item = next((x for x in store.list_credit_packs() if x["slug"] == slug), None)
        if not item:
            raise HTTPException(status_code=404, detail="credit pack not found")
        amount_paise = int(item["price_inr"]) * 100
        plan_slug = None
        pack_slug = slug
    elif purpose == "subscription":
        item = next((x for x in store.list_plans() if x["slug"] == slug), None)
        if not item or int(item["monthly_price_inr"]) <= 0:
            raise HTTPException(status_code=404, detail="paid plan not found")
        amount_paise = int(item["monthly_price_inr"]) * 100
        plan_slug = slug
        pack_slug = None
    else:
        raise HTTPException(status_code=400, detail="invalid purpose")
    try:
        key_id, key_secret, _ = _razorpay_config()
    except ControlError as exc:
        raise _json_error(exc) from exc
    receipt = f"ih_{user['id'][-10:]}_{secrets.token_hex(5)}"
    async with httpx.AsyncClient(timeout=20.0, auth=(key_id, key_secret)) as client:
        response = await client.post(
            "https://api.razorpay.com/v1/orders",
            json={"amount": amount_paise, "currency": "INR", "receipt": receipt, "notes": {"ih_user_id": user["id"], "purpose": purpose, "slug": slug}},
        )
    if not response.is_success:
        raise HTTPException(status_code=502, detail="Razorpay order creation failed")
    order = response.json()
    row = store.create_payment(
        user_id=user["id"],
        order_id=order["id"],
        amount_paise=amount_paise,
        purpose=purpose,
        plan_slug=plan_slug,
        credit_pack_slug=pack_slug,
        metadata={"receipt": receipt},
    )
    return {"order": order, "payment": row, "key_id": key_id}


@router.post("/api/billing/verify")
async def billing_verify(request: Request):
    user = _require_user(request)
    body = await request.json()
    order_id = str(body.get("razorpay_order_id") or "")
    payment_id = str(body.get("razorpay_payment_id") or "")
    signature = str(body.get("razorpay_signature") or "")
    try:
        key_id, key_secret, _ = _razorpay_config()
    except ControlError as exc:
        raise _json_error(exc) from exc
    expected = hmac.new(key_secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=400, detail="invalid payment signature")
    payment_row = store.get_payment_by_order(order_id)
    if not payment_row or payment_row["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="payment order not found")
    async with httpx.AsyncClient(timeout=20.0, auth=(key_id, key_secret)) as client:
        payment_resp = await client.get(f"https://api.razorpay.com/v1/payments/{payment_id}")
    if not payment_resp.is_success or payment_resp.json().get("status") not in {"captured", "authorized"}:
        raise HTTPException(status_code=409, detail="payment has not been confirmed by Razorpay")
    result = store.finalize_payment(order_id=order_id, payment_id=payment_id, status=payment_resp.json().get("status", "captured"))
    return {"ok": True, "payment": result, "wallet": store.wallet_ledger(user["id"], 20)["wallet"]}


@router.post("/api/webhooks/razorpay")
async def razorpay_webhook(request: Request):
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
    event_id = str(payment_entity.get("id") or order_entity.get("id") or payload_hash)
    inserted = store.record_webhook(
        provider="razorpay", event_id=event_id, event_type=event_type, signature_valid=valid, payload_hash=payload_hash, status="received" if valid else "rejected"
    )
    if not valid:
        raise HTTPException(status_code=400, detail="invalid webhook signature")
    if not inserted:
        return {"ok": True, "duplicate": True}
    if event_type in {"payment.captured", "order.paid"}:
        order_id = str(payment_entity.get("order_id") or order_entity.get("id") or "")
        payment_id = str(payment_entity.get("id") or "")
        if order_id and payment_id and store.get_payment_by_order(order_id):
            store.finalize_payment(order_id=order_id, payment_id=payment_id, status="captured")
    return {"ok": True}


@router.get("/api/status")
def public_status():
    return {
        "service": "Internet Hands",
        "control_database": store.configured,
        "mcp": "/mcp",
        "oauth": True,
        "billing": bool(os.getenv("RAZORPAY_KEY_ID") and os.getenv("RAZORPAY_KEY_SECRET")),
        "github_oauth": bool(os.getenv("GITHUB_CLIENT_ID") and os.getenv("GITHUB_CLIENT_SECRET")),
        "time": datetime.now(UTC).isoformat(),
    }
