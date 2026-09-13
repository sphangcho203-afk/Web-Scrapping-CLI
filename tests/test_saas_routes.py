from __future__ import annotations

from internet_hands.saas_app import app


def test_hardened_billing_routes_precede_initial_control_routes() -> None:
    paths = [getattr(route, "path", None) for route in app.routes]
    first_verify = paths.index("/api/billing/verify")
    later_verify = paths.index("/api/billing/verify", first_verify + 1)
    assert first_verify < later_verify

    first_webhook = paths.index("/api/webhooks/razorpay")
    later_webhook = paths.index("/api/webhooks/razorpay", first_webhook + 1)
    assert first_webhook < later_webhook


def test_reset_password_page_is_registered() -> None:
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/reset-password" in paths
    assert "/api/auth/password-reset/request" in paths
    assert "/api/auth/password-reset/confirm" in paths
