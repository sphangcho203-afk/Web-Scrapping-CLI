from internet_hands.telemetry import SqliteTelemetry


def test_sqlite_telemetry_orders_and_pages_events(tmp_path):
    telemetry = SqliteTelemetry(tmp_path / "telemetry.db")

    first = telemetry.emit(
        "job_started",
        worker_id="worker-a",
        backend="native",
        job_id=1,
        url="https://example.com/",
        payload={"attempt": 1},
    )
    second = telemetry.emit(
        "job_completed",
        worker_id="worker-a",
        backend="native",
        job_id=1,
        url="https://example.com/",
        payload={"discovered": 3},
    )

    assert second > first
    events = telemetry.list_events(after_id=0, limit=10)
    assert [event.event_type for event in events] == ["job_started", "job_completed"]
    assert events[0].payload == {"attempt": 1}
    assert events[1].payload == {"discovered": 3}

    tail = telemetry.list_events(after_id=first, limit=10)
    assert [event.id for event in tail] == [second]
