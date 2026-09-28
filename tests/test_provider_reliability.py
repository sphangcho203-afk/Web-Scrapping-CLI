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



class _SharedReliability:
    configured = True

    def __init__(self, rows=None, *, fail=False):
        self.rows = rows or {}
        self.fail = fail
        self.reset_calls = []
        self.snapshot_calls = 0

    def snapshot(self):
        self.snapshot_calls += 1
        if self.fail:
            raise RuntimeError("shared store unavailable")
        return self.rows

    def reset(self, provider=None):
        self.reset_calls.append(provider)


def test_shared_open_circuit_affects_runtime_routing() -> None:
    shared = _SharedReliability(
        {
            "exa": {
                "provider": "exa",
                "successes": 0,
                "failures": 3,
                "neutral": 0,
                "consecutive_failures": 3,
                "ewma_latency_ms": 900.0,
                "last_success_at": None,
                "last_failure_at": 1000.0,
                "last_error": "shared upstream failure",
                "last_error_class": "upstream_unavailable",
                "circuit_open_until": 2000.0,
            }
        }
    )
    tracker = ProviderReliabilityTracker(shared_store=shared)

    state = tracker.routing_state("exa", now=1500.0)

    assert state["circuit_open"] is True
    assert state["routing_penalty"] == 100_000
    assert state["consecutive_failures"] == 3
    assert shared.snapshot_calls == 1


def test_local_and_shared_health_merge_conservatively() -> None:
    shared = _SharedReliability(
        {
            "tavily": {
                "provider": "tavily",
                "successes": 9,
                "failures": 1,
                "neutral": 0,
                "consecutive_failures": 0,
                "ewma_latency_ms": 120.0,
                "last_success_at": 1000.0,
                "last_failure_at": 900.0,
                "last_error": None,
                "last_error_class": None,
                "circuit_open_until": 0.0,
            }
        }
    )
    tracker = ProviderReliabilityTracker(shared_store=shared)
    tracker.record(
        "tavily",
        status="failed",
        error="local timeout",
        error_class="timeout",
        duration_ms=5000,
        now=1100.0,
    )

    snapshot = tracker.snapshot("tavily", now=1101.0)

    assert snapshot["scope"] == "runtime+shared"
    assert snapshot["routing_penalty"] >= snapshot["local"]["routing_penalty"]
    assert snapshot["score"] == min(
        snapshot["local"]["score"],
        snapshot["shared"]["score"],
    )
    assert snapshot["local"]["last_error_class"] == "timeout"


def test_shared_store_failure_falls_back_to_local_state() -> None:
    shared = _SharedReliability(fail=True)
    tracker = ProviderReliabilityTracker(shared_store=shared)
    tracker.record("nativeweb", status="completed", duration_ms=100, now=1000.0)

    state = tracker.routing_state("nativeweb", now=1001.0)
    diagnostics = tracker.diagnostics()

    assert state["circuit_open"] is False
    assert state["samples"] == 1
    assert "shared store unavailable" in (diagnostics["shared_error"] or "")


def test_shared_snapshot_uses_short_ttl_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_SHARED_REFRESH_SECONDS", "30")
    shared = _SharedReliability({})
    tracker = ProviderReliabilityTracker(shared_store=shared)

    tracker.snapshot("exa", now=1000.0)
    tracker.snapshot("exa", now=1010.0)
    assert shared.snapshot_calls == 1

    tracker.snapshot("exa", now=1031.0)
    assert shared.snapshot_calls == 2


def test_reset_clears_local_and_shared_state() -> None:
    shared = _SharedReliability({})
    tracker = ProviderReliabilityTracker(shared_store=shared)
    tracker.record("exa", status="failed", now=1000.0)

    tracker.reset("exa")

    assert tracker.snapshot("exa", now=1001.0)["samples"] == 0
    assert shared.reset_calls == ["exa"]
