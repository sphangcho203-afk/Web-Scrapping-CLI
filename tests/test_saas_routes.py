from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from internet_hands.saas_app import app


def _paths(routes: Iterable[Any], prefix: str = "") -> list[str]:
    found: list[str] = []
    for route in routes:
        path = str(getattr(route, "path", "") or "")
        nested = getattr(route, "routes", None)
        full = f"{prefix}{path}" if path else prefix
        if nested:
            found.extend(_paths(nested, full))
        elif full:
            found.append(full)
    return found


def test_hardened_billing_routes_precede_initial_control_routes() -> None:
    paths = _paths(app.routes)
    first_verify = paths.index("/api/billing/verify")
    later_verify = paths.index("/api/billing/verify", first_verify + 1)
    assert first_verify < later_verify

    first_webhook = paths.index("/api/webhooks/razorpay")
    later_webhook = paths.index("/api/webhooks/razorpay", first_webhook + 1)
    assert first_webhook < later_webhook


def test_reset_password_page_is_registered() -> None:
    paths = set(_paths(app.routes))
    assert "/reset-password" in paths
    assert "/api/auth/password-reset/request" in paths
    assert "/api/auth/password-reset/confirm" in paths
