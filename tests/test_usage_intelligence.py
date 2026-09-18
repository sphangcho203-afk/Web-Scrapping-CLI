from __future__ import annotations

from pathlib import Path

import pytest

from internet_hands.usage_intelligence import WINDOWS, normalize_window

ROOT = Path(__file__).resolve().parents[1]


def test_usage_windows_are_explicit_and_stable() -> None:
    assert list(WINDOWS) == ["24h", "7d", "30d", "90d"]
    assert normalize_window(" 7D ") == "7d"


def test_invalid_usage_window_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported usage window"):
        normalize_window("all")


def test_usage_api_is_registered_in_saas_app() -> None:
    source = (ROOT / "src/internet_hands/saas_app.py").read_text(encoding="utf-8")
    api = (ROOT / "src/internet_hands/usage_api.py").read_text(encoding="utf-8")
    assert "from .usage_api import router as usage_router" in source
    assert "app.include_router(usage_router)" in source
    assert '@router.get("/api/usage/intelligence")' in api
