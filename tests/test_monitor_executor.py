from __future__ import annotations

import pytest
from fastapi import HTTPException

from internet_hands import monitor_executor


def test_cron_requires_configured_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRON_SECRET", raising=False)
    with pytest.raises(HTTPException) as exc:
        monitor_executor._cron_authorized(None)
    assert exc.value.status_code == 503


def test_cron_rejects_wrong_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRON_SECRET", "expected")
    with pytest.raises(HTTPException) as exc:
        monitor_executor._cron_authorized("Bearer wrong")
    assert exc.value.status_code == 401
    monitor_executor._cron_authorized("Bearer expected")


def test_monitor_timeout_is_bounded() -> None:
    assert monitor_executor._timeout_for({"config": {"timeout_seconds": 0}}) == 1.0
    assert monitor_executor._timeout_for({"config": {"timeout_seconds": 999}}) == 20.0
    assert monitor_executor._timeout_for({"config": {"timeout_seconds": "bad"}}) == 10.0


def test_execution_plane_uses_skip_locked_and_public_fetcher() -> None:
    source = open("src/internet_hands/monitor_executor.py", encoding="utf-8").read()
    assert "FOR UPDATE SKIP LOCKED" in source
    assert "health_check(target" in source
    assert "next_check_at = now()" in source
    assert "ih_monitor_runs" in source
    assert "last_checked_at" in source


def test_scheduler_route_is_registered() -> None:
    source = open("src/internet_hands/saas_app.py", encoding="utf-8").read()
    executor = open("src/internet_hands/monitor_executor.py", encoding="utf-8").read()
    assert "monitor_executor_router" in source
    assert 'router.get("/api/internal/monitors/tick")' in executor
    assert "CRON_SECRET" in executor
