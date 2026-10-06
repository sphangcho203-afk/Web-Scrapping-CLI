from __future__ import annotations

import os
import time
from typing import Any

import httpx

_VAULT_SECRET_CACHE: dict[str, tuple[float, str]] = {}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _http_header_secret(value: Any) -> str | None:
    normalized = _clean(value)
    if not normalized or not normalized.isascii():
        return None
    if any(ord(char) < 33 or ord(char) == 127 for char in normalized):
        return None
    return normalized


def supabase_vault_secret(name: str, *, ttl_seconds: float = 60.0) -> str | None:
    """Resolve one server-side Supabase Vault secret through the service-role-only RPC."""
    normalized = name.strip()
    if not normalized:
        return None

    now = time.monotonic()
    cached = _VAULT_SECRET_CACHE.get(normalized)
    if cached is not None and now - cached[0] < ttl_seconds:
        return cached[1]

    url = _clean(os.getenv("SUPABASE_URL"))
    service_key = _http_header_secret(os.getenv("SUPABASE_SECRET_KEY")) or _http_header_secret(
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    )
    if not url or not service_key:
        return None

    try:
        response = httpx.post(
            f"{url.rstrip('/')}/rest/v1/rpc/open_crawl_get_vault_secret",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
            },
            json={"p_secret_name": normalized},
            timeout=5.0,
        )
    except (httpx.HTTPError, UnicodeError, ValueError):
        return None
    if not response.is_success:
        return None

    try:
        value = _clean(response.json())
    except ValueError:
        return None
    if value:
        _VAULT_SECRET_CACHE[normalized] = (now, value)
    return value


def clear_vault_secret_cache() -> None:
    _VAULT_SECRET_CACHE.clear()
