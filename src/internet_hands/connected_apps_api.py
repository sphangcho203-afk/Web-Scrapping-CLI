from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request

from .control_api import _origin, _require_user, _require_verified

router = APIRouter()
COMPOSIO_BASE_URL = "https://backend.composio.dev/api/v3.1"
_TOOLKIT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def _toolkit_slug(value: Any) -> str:
    slug = str(value or "").strip().lower()
    if not _TOOLKIT_RE.fullmatch(slug):
        raise HTTPException(status_code=400, detail="invalid integration toolkit")
    return slug


def _configured_auth_map() -> dict[str, str]:
    raw = (os.getenv("OPENCRAWL_COMPOSIO_AUTH_CONFIGS") or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OPENCRAWL_COMPOSIO_AUTH_CONFIGS must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise TypeError("OPENCRAWL_COMPOSIO_AUTH_CONFIGS must be a JSON object")
    return {
        _toolkit_slug(key): str(value).strip()
        for key, value in payload.items()
        if str(value).strip()
    }


def _public_connection(item: dict[str, Any]) -> dict[str, Any]:
    toolkit = item.get("toolkit") if isinstance(item.get("toolkit"), dict) else {}
    auth_config = item.get("auth_config") if isinstance(item.get("auth_config"), dict) else {}
    return {
        "id": str(item.get("id") or item.get("connected_account_id") or ""),
        "toolkit": str(toolkit.get("slug") or item.get("toolkit_slug") or ""),
        "alias": str(item.get("alias") or item.get("name") or "") or None,
        "status": str(item.get("status") or "UNKNOWN").upper(),
        "status_reason": str(item.get("status_reason") or "")[:240] or None,
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "auth_config": {
            "id": str(auth_config.get("id") or item.get("auth_config_id") or "") or None,
            "auth_scheme": auth_config.get("auth_scheme"),
            "is_composio_managed": auth_config.get("is_composio_managed"),
        },
    }


class ComposioConnectionService:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = COMPOSIO_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("COMPOSIO_API_KEY", "")).strip()
        self.base_url = base_url.rstrip("/")
        self.client = client

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise HTTPException(status_code=503, detail="connected apps are not configured")
        return {"x-api-key": self.api_key, "Accept": "application/json"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        client = self.client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=20.0)
        try:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(),
                **kwargs,
            )
        finally:
            if owns_client:
                await client.aclose()
        if response.is_success:
            return response
        if response.status_code in {401, 403}:
            raise HTTPException(status_code=503, detail="connected apps provider authorization failed")
        if response.status_code == 429:
            raise HTTPException(status_code=503, detail="connected apps provider is rate limited")
        detail = "connected apps provider request failed"
        try:
            payload = response.json()
            message = payload.get("message") or payload.get("detail") or payload.get("error")
            if isinstance(message, str) and message.strip():
                detail = message.strip()[:240]
        except (ValueError, TypeError):
            pass
        raise HTTPException(status_code=502, detail=detail)

    async def auth_configs(self, toolkit: str | None = None) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        cursor: str | None = None
        pages = 0
        while True:
            params: dict[str, Any] = {"limit": 50, "show_disabled": "false"}
            if toolkit:
                params["toolkit_slug"] = toolkit
            if cursor:
                params["cursor"] = cursor
            response = await self._request("GET", "/auth_configs", params=params)
            payload = response.json()
            items = payload.get("items") if isinstance(payload, dict) else []
            output.extend(item for item in (items or []) if isinstance(item, dict))
            cursor = str(payload.get("next_cursor") or payload.get("nextCursor") or "") if isinstance(payload, dict) else ""
            pages += 1
            if not cursor or pages >= 20:
                break
        return output

    async def user_connections(
        self,
        user_id: str,
        *,
        toolkit: str | None = None,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        cursor: str | None = None
        pages = 0
        while True:
            params: list[tuple[str, str]] = [("limit", "100"), ("user_ids", user_id)]
            if toolkit:
                params.append(("toolkit_slugs", toolkit))
            if account_id:
                params.append(("connected_account_ids", account_id))
            if cursor:
                params.append(("cursor", cursor))
            response = await self._request("GET", "/connected_accounts", params=params)
            payload = response.json()
            items = payload.get("items") if isinstance(payload, dict) else []
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                # Never trust upstream filtering as the tenant boundary.
                if str(item.get("user_id") or item.get("userId") or "") != user_id:
                    continue
                output.append(item)
            cursor = str(payload.get("next_cursor") or payload.get("nextCursor") or "") if isinstance(payload, dict) else ""
            pages += 1
            if not cursor or pages >= 20:
                break
        return output

    async def resolve_auth_config(
        self,
        toolkit: str,
        requested_id: str | None = None,
    ) -> dict[str, Any]:
        configs = [
            item
            for item in await self.auth_configs(toolkit)
            if str(item.get("status") or "ENABLED").upper() == "ENABLED"
            and str((item.get("toolkit") or {}).get("slug") or "").lower() == toolkit
        ]
        configured = _configured_auth_map().get(toolkit)
        selected_id = str(requested_id or configured or "").strip()
        if selected_id:
            match = next((item for item in configs if str(item.get("id") or "") == selected_id), None)
            if match is None:
                raise HTTPException(status_code=400, detail="auth config is not enabled for this toolkit")
            return match
        if len(configs) == 1:
            return configs[0]
        if not configs:
            raise HTTPException(status_code=409, detail="no enabled auth config exists for this toolkit")
        raise HTTPException(
            status_code=409,
            detail={
                "code": "integration_auth_config_ambiguous",
                "message": "multiple auth configs exist; configure a default before exposing this toolkit",
            },
        )

    async def create_link(
        self,
        *,
        user_id: str,
        toolkit: str,
        alias: str | None = None,
        auth_config_id: str | None = None,
        callback_url: str | None = None,
        allow_multiple: bool = False,
    ) -> dict[str, Any]:
        config = await self.resolve_auth_config(toolkit, auth_config_id)
        config_id = str(config["id"])
        if not allow_multiple:
            existing = await self.user_connections(user_id, toolkit=toolkit)
            active_same_config = [
                item
                for item in existing
                if str(item.get("status") or "").upper() == "ACTIVE"
                and str(
                    ((item.get("auth_config") or {}).get("id"))
                    if isinstance(item.get("auth_config"), dict)
                    else item.get("auth_config_id") or ""
                )
                == config_id
            ]
            if active_same_config:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "integration_account_exists",
                        "message": (
                            "an active account already exists for this authentication "
                            "configuration; explicitly choose connect another account"
                        ),
                    },
                )
        body: dict[str, Any] = {
            "auth_config_id": config_id,
            "user_id": user_id,
        }
        if alias:
            body["alias"] = alias[:80]
        if callback_url:
            body["callback_url"] = callback_url
        response = await self._request("POST", "/connected_accounts/link", json=body)
        payload = response.json()
        redirect_url = str(payload.get("redirect_url") or "")
        if not redirect_url.startswith("https://"):
            raise HTTPException(status_code=502, detail="provider returned an invalid authorization URL")
        return {
            "toolkit": toolkit,
            "auth_config_id": str(config["id"]),
            "redirect_url": redirect_url,
            "expires_at": payload.get("expires_at"),
            "connected_account_id": payload.get("connected_account_id"),
        }

    async def reconnect_link(
        self,
        *,
        user_id: str,
        account_id: str,
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        owned = await self.user_connections(user_id, account_id=account_id)
        account = next(
            (item for item in owned if str(item.get("id") or "") == account_id),
            None,
        )
        if account is None:
            raise HTTPException(status_code=404, detail="connected account not found")
        toolkit = _toolkit_slug(
            (account.get("toolkit") or {}).get("slug")
            if isinstance(account.get("toolkit"), dict)
            else account.get("toolkit_slug")
        )
        auth_config = (
            account.get("auth_config")
            if isinstance(account.get("auth_config"), dict)
            else {}
        )
        auth_config_id = str(
            auth_config.get("id") or account.get("auth_config_id") or ""
        ).strip() or None
        return await self.create_link(
            user_id=user_id,
            toolkit=toolkit,
            alias=None,
            auth_config_id=auth_config_id,
            callback_url=callback_url,
            allow_multiple=False,
        )

    async def disconnect(self, *, user_id: str, account_id: str) -> None:
        owned = await self.user_connections(user_id, account_id=account_id)
        if not any(str(item.get("id") or "") == account_id for item in owned):
            raise HTTPException(status_code=404, detail="connected account not found")
        await self._request("DELETE", f"/connected_accounts/{account_id}")


@router.get("/api/integrations/apps")
async def integration_apps(request: Request):
    user = _require_user(request)
    service = ComposioConnectionService()
    if not service.configured:
        return {"configured": False, "apps": [], "connections": []}
    configs = await service.auth_configs()
    connections = await service.user_connections(str(user["id"]))
    by_toolkit: dict[str, dict[str, Any]] = {}
    for item in configs:
        if str(item.get("status") or "ENABLED").upper() != "ENABLED":
            continue
        toolkit = item.get("toolkit") if isinstance(item.get("toolkit"), dict) else {}
        slug = str(toolkit.get("slug") or "").lower()
        if not slug or not _TOOLKIT_RE.fullmatch(slug):
            continue
        entry = by_toolkit.setdefault(
            slug,
            {
                "toolkit": slug,
                "name": str(
                    toolkit.get("name")
                    or item.get("name")
                    or slug.replace("_", " ").title()
                ),
                "logo": toolkit.get("logo"),
                "auth_schemes": [],
                "auth_configs": [],
                "auth_config_count": 0,
                "connected_accounts": 0,
                "active_accounts": 0,
            },
        )
        entry["auth_config_count"] += 1
        scheme = str(item.get("auth_scheme") or "")
        if scheme and scheme not in entry["auth_schemes"]:
            entry["auth_schemes"].append(scheme)
        config_id = str(item.get("id") or "").strip()
        if config_id:
            entry["auth_configs"].append(
                {
                    "id": config_id,
                    "name": str(item.get("name") or config_id),
                    "auth_scheme": scheme or None,
                    "is_composio_managed": bool(item.get("is_composio_managed")),
                }
            )
    public_connections = [_public_connection(item) for item in connections]
    for connection in public_connections:
        entry = by_toolkit.get(str(connection["toolkit"]))
        if entry is not None:
            entry["connected_accounts"] += 1
            status = str(connection.get("status") or "UNKNOWN").upper()
            entry.setdefault("status_counts", {})
            entry["status_counts"][status] = int(entry["status_counts"].get(status) or 0) + 1
            if status == "ACTIVE":
                entry["active_accounts"] = int(entry.get("active_accounts") or 0) + 1
    return {
        "configured": True,
        "apps": sorted(by_toolkit.values(), key=lambda item: (item["name"], item["toolkit"])),
        "connections": public_connections,
    }


@router.post("/api/integrations/{toolkit}/connect")
async def integration_connect(toolkit: str, request: Request):
    user = _require_verified(_require_user(request))
    slug = _toolkit_slug(toolkit)
    body = await request.json()
    alias = str(body.get("alias") or "").strip() or None
    auth_config_id = str(body.get("auth_config_id") or "").strip() or None
    allow_multiple = body.get("allow_multiple") is True
    callback_url = f"{_origin(request)}/dashboard/connections?connected={slug}"
    service = ComposioConnectionService()
    return await service.create_link(
        user_id=str(user["id"]),
        toolkit=slug,
        alias=alias,
        auth_config_id=auth_config_id,
        callback_url=callback_url,
        allow_multiple=allow_multiple,
    )


@router.get("/api/integrations/connections")
async def integration_connections(request: Request):
    user = _require_user(request)
    service = ComposioConnectionService()
    if not service.configured:
        return {"configured": False, "connections": []}
    rows = await service.user_connections(str(user["id"]))
    return {"configured": True, "connections": [_public_connection(item) for item in rows]}


@router.post("/api/integrations/connections/{account_id}/reconnect")
async def integration_reconnect(account_id: str, request: Request):
    user = _require_verified(_require_user(request))
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", account_id):
        raise HTTPException(status_code=400, detail="invalid connected account id")
    service = ComposioConnectionService()
    callback_url = f"{_origin(request)}/dashboard/connections?reconnected=1"
    return await service.reconnect_link(
        user_id=str(user["id"]),
        account_id=account_id,
        callback_url=callback_url,
    )


@router.delete("/api/integrations/connections/{account_id}")
async def integration_disconnect(account_id: str, request: Request):
    user = _require_verified(_require_user(request))
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", account_id):
        raise HTTPException(status_code=400, detail="invalid connected account id")
    service = ComposioConnectionService()
    await service.disconnect(user_id=str(user["id"]), account_id=account_id)
    return {"ok": True}
