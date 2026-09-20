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
    assert '@router.get("/api/usage/runs/{request_id}")' in api


def test_run_detail_is_user_scoped_and_exposes_trace_fields() -> None:
    source = (ROOT / "src/internet_hands/usage_intelligence.py").read_text(encoding="utf-8")
    assert "WHERE e.user_id=%s AND e.request_id=%s" in source
    for field in ("input_bytes", "output_bytes", "metadata", "api_key_name", "api_key_environment"):
        assert field in source


def test_usage_snapshot_exposes_daily_series_and_status_breakdown() -> None:
    source = (ROOT / "src/internet_hands/usage_intelligence.py").read_text(encoding="utf-8")
    assert "date_trunc('day',created_at)::date AS bucket" in source
    assert 'by_status = breakdown("status")' in source
    assert '"series": series' in source
    assert '"status": by_status' in source


def test_usage_ui_supports_deep_linked_run_detail() -> None:
    source = (ROOT / "web/usage-intelligence.js").read_text(encoding="utf-8")
    assert "/api/usage/runs/" in source
    assert "searchParams.set('run', requestId)" in source
    assert "RUN DETAIL" in source
    assert "RUN METADATA" in source


def test_usage_ui_renders_server_backed_trend_and_status_intelligence() -> None:
    source = (ROOT / "web/usage-intelligence.js").read_text(encoding="utf-8")
    assert "const trend = rows =>" in source
    assert "Usage over time" in source
    assert "Request volume trend" in source
    assert "Credit burn trend" in source
    assert "data.series||[]" in source
    assert "breakdown('By status',b.status||[])" in source
    assert "Nothing is fabricated" in source
