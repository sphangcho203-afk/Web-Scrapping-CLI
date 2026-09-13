from __future__ import annotations

from pathlib import Path

from internet_hands.control_hardening import router as hardening_router
from internet_hands.site import router as site_router


def _router_paths(router) -> list[str]:
    return [str(getattr(route, "path", "") or "") for route in router.routes]


def test_hardened_billing_routes_are_registered() -> None:
    paths = _router_paths(hardening_router)
    assert "/api/billing/verify" in paths
    assert "/api/webhooks/razorpay" in paths


def test_reset_password_surface_is_registered() -> None:
    site_paths = set(_router_paths(site_router))
    hardening_paths = set(_router_paths(hardening_router))
    assert "/reset-password" in site_paths
    assert "/api/auth/password-reset/request" in hardening_paths
    assert "/api/auth/password-reset/confirm" in hardening_paths


def test_vercel_entrypoint_uses_saas_app() -> None:
    text = Path("app.py").read_text(encoding="utf-8")
    assert "from internet_hands.saas_app import app" in text
