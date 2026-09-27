from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from internet_hands.provider_reliability_store import (
    record_provider_reliability_event,
)


class _Cursor:
    def __init__(self) -> None:
        self.row = None
        self._selected = None

    def execute(self, sql: str, params=()) -> None:
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("select provider,successes"):
            provider = params[0]
            self._selected = (
                dict(self.row)
                if self.row is not None and self.row["provider"] == provider
                else None
            )
            return
        if normalized.startswith("insert into ih_provider_reliability"):
            (
                provider,
                successes,
                failures,
                neutral,
                streak,
                ewma,
                last_success,
                last_failure,
                last_error,
                last_error_class,
                circuit_until,
                updated_at,
            ) = params
            self.row = {
                "provider": provider,
                "successes": successes,
                "failures": failures,
                "neutral": neutral,
                "consecutive_failures": streak,
                "ewma_latency_ms": ewma,
                "last_success_at": last_success,
                "last_failure_at": last_failure,
                "last_error": last_error,
                "last_error_class": last_error_class,
                "circuit_open_until": circuit_until,
                "updated_at": updated_at,
            }
            return
        raise AssertionError(f"unexpected SQL: {normalized}")

    def fetchone(self):
        return self._selected


def _event(
    status: str,
    *,
    error: str | None = None,
    error_class: str | None = None,
    duration_ms: int = 100,
) -> dict:
    return {
        "provider": "exa",
        "ref": "exa:search",
        "status": status,
        "duration_ms": duration_ms,
        "error": error,
        "error_class": error_class,
        "retryable": status == "failed",
        "attempt": 1,
    }


def test_shared_reliability_opens_and_heals_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_CIRCUIT_FAILURES", "3")
    monkeypatch.setenv("OPENCRAWL_PROVIDER_CIRCUIT_COOLDOWN_SECONDS", "45")
    cursor = _Cursor()
    start = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)

    for offset in range(3):
        record_provider_reliability_event(
            cursor,
            _event(
                "failed",
                error="upstream unavailable",
                error_class="upstream_unavailable",
                duration_ms=100 + offset * 10,
            ),
            now=start + timedelta(seconds=offset),
        )

    assert cursor.row["failures"] == 3
    assert cursor.row["successes"] == 0
    assert cursor.row["consecutive_failures"] == 3
    assert cursor.row["last_error_class"] == "upstream_unavailable"
    assert cursor.row["circuit_open_until"] == start + timedelta(seconds=47)

    record_provider_reliability_event(
        cursor,
        _event("completed", duration_ms=80),
        now=start + timedelta(seconds=3),
    )

    assert cursor.row["successes"] == 1
    assert cursor.row["failures"] == 3
    assert cursor.row["consecutive_failures"] == 0
    assert cursor.row["last_error"] is None
    assert cursor.row["last_error_class"] is None
    assert cursor.row["circuit_open_until"] is None


def test_shared_blocked_outcome_is_neutral() -> None:
    cursor = _Cursor()
    now = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)

    record_provider_reliability_event(
        cursor,
        _event(
            "blocked",
            error="captcha",
            error_class="blocked",
        ),
        now=now,
    )

    assert cursor.row["neutral"] == 1
    assert cursor.row["failures"] == 0
    assert cursor.row["consecutive_failures"] == 0
    assert cursor.row["circuit_open_until"] is None


def test_shared_latency_uses_ewma() -> None:
    cursor = _Cursor()
    now = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)

    record_provider_reliability_event(
        cursor,
        _event("completed", duration_ms=100),
        now=now,
    )
    record_provider_reliability_event(
        cursor,
        _event("completed", duration_ms=500),
        now=now + timedelta(seconds=1),
    )

    assert cursor.row["ewma_latency_ms"] == pytest.approx(180.0)
