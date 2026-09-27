from __future__ import annotations

import pytest

from internet_hands.provider_reliability import ProviderReliabilityTracker


def test_provider_reliability_opens_circuit_after_failure_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_CIRCUIT_FAILURES", "3")
    monkeypatch.setenv("OPENCRAWL_PROVIDER_CIRCUIT_COOLDOWN_SECONDS", "45")
    tracker = ProviderReliabilityTracker()

    tracker.record("exa", status="failed", error="one", now=1000)
    tracker.record("exa", status="failed", error="two", now=1001)
    before = tracker.record("exa", status="failed", error="three", now=1002)

    assert before["failures"] == 3
    assert before["consecutive_failures"] == 3
    assert before["circuit_open"] is True
    assert before["circuit_remaining_seconds"] == 45
    assert before["last_error"] == "three"
    assert before["routing_penalty"] == 100_000


def test_success_heals_open_circuit_and_failure_streak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_CIRCUIT_FAILURES", "2")
    tracker = ProviderReliabilityTracker()

    tracker.record("tavily", status="failed", error="one", now=1000)
    tracker.record("tavily", status="failed", error="two", now=1001)
    assert tracker.snapshot("tavily", now=1002)["circuit_open"] is True

    healed = tracker.record(
        "tavily",
        status="completed",
        duration_ms=220,
        now=1003,
    )

    assert healed["successes"] == 1
    assert healed["consecutive_failures"] == 0
    assert healed["circuit_open"] is False
    assert healed["last_error"] is None


def test_blocked_target_is_neutral_not_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_CIRCUIT_FAILURES", "2")
    tracker = ProviderReliabilityTracker()

    first = tracker.record(
        "intelligence",
        status="blocked",
        error="captcha",
        duration_ms=90,
        now=1000,
    )
    second = tracker.record(
        "intelligence",
        status="blocked",
        error="access denied",
        duration_ms=100,
        now=1001,
    )

    assert first["neutral"] == 1
    assert second["neutral"] == 2
    assert second["failures"] == 0
    assert second["consecutive_failures"] == 0
    assert second["circuit_open"] is False


def test_reliability_score_uses_latency_and_failure_history() -> None:
    tracker = ProviderReliabilityTracker()
    clean = tracker.snapshot("brave", now=1000)
    assert clean["samples"] == 0
    assert clean["routing_penalty"] == 0

    success = tracker.record(
        "brave",
        status="completed",
        duration_ms=100,
        now=1001,
    )
    failure = tracker.record(
        "brave",
        status="failed",
        duration_ms=5000,
        error="timeout",
        now=1002,
    )

    assert success["score"] >= 75
    assert failure["samples"] == 2
    assert failure["routing_penalty"] > 0
    assert failure["ewma_latency_ms"] > 100


def test_reset_can_clear_one_provider_or_all() -> None:
    tracker = ProviderReliabilityTracker()
    tracker.record("exa", status="failed", now=1000)
    tracker.record("tavily", status="failed", now=1000)

    tracker.reset("exa")
    assert tracker.snapshot("exa", now=1001)["samples"] == 0
    assert tracker.snapshot("tavily", now=1001)["samples"] == 1

    tracker.reset()
    assert tracker.snapshot() == {}
