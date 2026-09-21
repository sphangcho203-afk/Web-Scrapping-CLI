from __future__ import annotations

from pathlib import Path

from internet_hands import phone_api

ROOT = Path(__file__).resolve().parents[1]


def test_phone_routes_are_mounted_on_production_app() -> None:
    paths = {getattr(route, "path", None) for route in phone_api.router.routes}
    assert paths == {
        "/api/auth/phone/providers",
        "/api/auth/phone/status",
        "/api/auth/phone/start",
        "/api/auth/phone/confirm",
        "/api/auth/phone/intelligence",
        "/api/auth/phone",
    }
    source = (ROOT / "src/internet_hands/saas_app.py").read_text(encoding="utf-8")
    assert "from .phone_api import router as phone_router" in source
    assert "app.include_router(phone_router)" in source


def test_phone_identity_does_not_implement_reverse_subscriber_lookup() -> None:
    source = (ROOT / "src/internet_hands/phone_identity.py").read_text(encoding="utf-8").lower()
    for forbidden in (
        "caller_name",
        "primary account holder",
        "subscriber_name",
        "person behind",
        "reverse identity",
    ):
        assert forbidden not in source


def test_phone_verification_persists_rate_limits_and_attempt_limits() -> None:
    source = (ROOT / "src/internet_hands/phone_store.py").read_text(encoding="utf-8")
    assert "ih_phone_verifications" in source
    assert "hourly_limit" in source
    assert "attempts=attempts+1" in source
    assert "phone_already_verified" in source
