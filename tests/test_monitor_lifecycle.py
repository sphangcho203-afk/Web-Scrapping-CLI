from __future__ import annotations

from pathlib import Path

import pytest

from internet_hands.monitor_lifecycle import validate_monitor_spec

ROOT = Path(__file__).resolve().parents[1]


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


def test_monitor_lifecycle_ui_is_composed_into_single_runtime() -> None:
    site = (ROOT / "src/internet_hands/site.py").read_text()
    ui = (ROOT / "web/monitor-lifecycle.js").read_text()
    index = (ROOT / "web/index.html").read_text()
    assert 'WEB_ROOT / "monitor-lifecycle.js"' in site
    assert index.count('/assets/app.js') == 1
    assert '/assets/monitor-lifecycle.js' not in index
    assert "'/api/monitors/validate'" in ui
    assert "'/api/monitors'" in ui
    assert "/history?limit=25" in ui
    assert "method:'PATCH'" in ui
    assert "/toggle" in ui
    assert "No fabricated health" in ui


def test_monitor_detail_surfaces_persisted_lifecycle_state() -> None:
    ui = (ROOT / "web/monitor-lifecycle.js").read_text()
    for marker in (
        "Last check",
        "Next check",
        "CHECK HISTORY",
        "Load older checks",
        "No persisted checks yet",
    ):
        assert marker in ui
