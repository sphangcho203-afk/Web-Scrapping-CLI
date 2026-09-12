from internet_hands import frontier
from internet_hands.frontier import FrontierStore, JobState
from internet_hands.rate_limit import DistributedHostLimiter


def test_frontier_lease_retry_ack_and_deduplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(frontier, "validate_public_http_url", lambda url: url)
    store = FrontierStore(tmp_path / "frontier.db")

    assert store.enqueue("https://example.com/a") is True
    assert store.enqueue("https://example.com/a") is False

    leased = store.lease("worker-a", limit=1, lease_seconds=30)
    assert len(leased) == 1
    assert leased[0].attempts == 1
    assert store.lease("worker-b", limit=1, lease_seconds=30) == []

    state = store.fail(
        leased[0].id,
        "worker-a",
        "temporary failure",
        base_backoff_seconds=0,
        max_backoff_seconds=0,
    )
    assert state == JobState.QUEUED

    leased_again = store.lease("worker-b", limit=1, lease_seconds=30)
    assert len(leased_again) == 1
    assert leased_again[0].attempts == 2
    assert store.ack(leased_again[0].id, "worker-b") is True
    assert store.stats()["done"] == 1


def test_frontier_circuit_breaker_state(tmp_path):
    store = FrontierStore(tmp_path / "frontier.db")
    assert store.circuit_allows("native:example.com") is True
    assert store.circuit_failure("native:example.com", "one", threshold=2) is False
    assert store.circuit_failure("native:example.com", "two", threshold=2) is True
    assert store.circuit_allows("native:example.com") is False
    store.circuit_success("native:example.com")
    assert store.circuit_allows("native:example.com") is True


def test_distributed_host_limiter_reserves_non_overlapping_slots(tmp_path):
    limiter = DistributedHostLimiter(tmp_path / "frontier.db")
    first = limiter.reserve("example.com", min_delay_seconds=1.0)
    second = limiter.reserve("example.com", min_delay_seconds=1.0)
    assert first == 0.0
    assert second > 0.5
