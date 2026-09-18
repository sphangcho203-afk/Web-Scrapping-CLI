from __future__ import annotations

import pytest

from internet_hands.usage_intelligence import WINDOWS, normalize_window


def test_usage_windows_are_explicit_and_stable() -> None:
    assert list(WINDOWS) == ["24h", "7d", "30d", "90d"]
    assert normalize_window(" 7D ") == "7d"


def test_invalid_usage_window_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported usage window"):
        normalize_window("all")


def test_usage_api_is_registered_in_saas_app() -> None:
    from internet_hands.saas_app import app

    paths = {route.path for route in app.routes}
    assert "/api/usage/intelligence" in paths
