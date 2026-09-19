from __future__ import annotations

import pytest

from internet_hands.monitor_lifecycle import validate_monitor_spec


def test_monitor_spec_normalizes_complete_web_monitor() -> None:
    result = validate_monitor_spec(
        {
            "name": "  Docs health  ",
            "type": "WEB",
            "target": "https://example.com/docs",
            "interval_minutes": 15,
            "config": {"alert_on_change": True},
        }
    )
    assert result == {
        "name": "Docs health",
        "type": "web",
        "target": "https://example.com/docs",
        "interval_minutes": 15,
        "config": {"alert_on_change": True},
    }


@pytest.mark.parametrize("monitor_type", ["web", "api", "mcp"])
def test_url_monitor_types_require_http_targets(monitor_type: str) -> None:
    with pytest.raises(ValueError, match=r"http\(s\) URL"):
        validate_monitor_spec(
            {
                "name": "Bad target",
                "type": monitor_type,
                "target": "file:///etc/passwd",
                "interval_minutes": 60,
            }
        )


def test_gaming_monitor_allows_provider_specific_target() -> None:
    result = validate_monitor_spec(
        {
            "name": "Rank watch",
            "type": "gaming",
            "target": "player:123456",
            "interval_minutes": 60,
        }
    )
    assert result["target"] == "player:123456"


@pytest.mark.parametrize("interval", [0, 4, 10081])
def test_monitor_interval_is_bounded(interval: int) -> None:
    with pytest.raises(ValueError, match="between 5 and 10080"):
        validate_monitor_spec(
            {
                "name": "Interval test",
                "type": "web",
                "target": "https://example.com",
                "interval_minutes": interval,
            }
        )


def test_partial_edit_requires_real_fields() -> None:
    with pytest.raises(ValueError, match="no editable monitor fields"):
        validate_monitor_spec({"ignored": True}, partial=True)


def test_partial_target_uses_current_type_for_validation() -> None:
    with pytest.raises(ValueError, match=r"http\(s\) URL"):
        validate_monitor_spec(
            {"target": "not-a-url", "current_type": "api"},
            partial=True,
        )
