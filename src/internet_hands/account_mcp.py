from __future__ import annotations

from typing import Any

from .auth import current_auth
from .control_store import ControlError, ControlStore
from .mcp_server import sandbox_mcp

store = ControlStore()


def _identity():
    identity = current_auth.get()
    if not identity:
        raise ControlError("unauthorized", "account context is unavailable", 401)
    return identity


@sandbox_mcp.tool()
def account_me() -> dict[str, Any]:
    """Return the authenticated Internet Hands account, plan, and entitlement summary."""
    identity = _identity()
    return store.account_snapshot(identity.user_id)


@sandbox_mcp.tool()
def account_usage() -> dict[str, Any]:
    """Return recent usage totals, credits, latency, and top tool activity for this account."""
    identity = _identity()
    return store.usage_summary(identity.user_id)


@sandbox_mcp.tool()
def account_wallet(limit: int = 40) -> dict[str, Any]:
    """Return monthly and purchased credit balances plus recent wallet ledger entries."""
    identity = _identity()
    return store.wallet_ledger(identity.user_id, limit=limit)


@sandbox_mcp.tool()
def account_limits() -> dict[str, Any]:
    """Return plan rate, API-key, monitor, browser, and sandbox limits for this account."""
    identity = _identity()
    account = store.account_snapshot(identity.user_id)
    return {
        "plan": account.get("plan_slug"),
        "rpm_limit": account.get("rpm_limit"),
        "concurrent_limit": account.get("concurrent_limit"),
        "api_key_limit": account.get("api_key_limit"),
        "monitor_limit": account.get("monitor_limit"),
        "browser_enabled": account.get("browser_enabled"),
        "sandbox_enabled": account.get("sandbox_enabled"),
    }


@sandbox_mcp.tool()
def monitors_list() -> dict[str, Any]:
    """List this account's configured Internet Hands monitors."""
    identity = _identity()
    return {"monitors": store.list_monitors(identity.user_id)}


@sandbox_mcp.tool()
def monitor_get(monitor_id: str) -> dict[str, Any]:
    """Return one monitor and its recent run history."""
    identity = _identity()
    monitor = store.get_monitor(identity.user_id, monitor_id)
    if not monitor:
        raise ControlError("monitor_not_found", "monitor not found", 404)
    return monitor
