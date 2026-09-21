from __future__ import annotations

from pathlib import Path

APP = Path("web/app.js")


def test_settings_surface_exposes_phone_verification() -> None:
    source = APP.read_text(encoding="utf-8")
    assert "PHONE IDENTITY" in source
    assert "/api/auth/phone/status" in source
    assert "/api/auth/phone/start" in source
    assert "/api/auth/phone/confirm" in source
    assert "/api/auth/phone/intelligence" in source
    assert "/api/auth/phone" in source
    assert "it does not identify the subscriber behind a SIM" in source


def test_phone_verification_is_not_a_signup_gate() -> None:
    source = APP.read_text(encoding="utf-8")
    assert "Phone ownership" in source
    assert "Optional" in source
