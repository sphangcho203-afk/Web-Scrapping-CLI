from datetime import UTC, datetime

from internet_hands.models import MonitorState


def test_monitor_state_json_roundtrip():
    state = MonitorState(
        url="https://example.com",
        sha256="a" * 64,
        checked_at=datetime.now(UTC),
        status_code=200,
        content_length=42,
    )
    restored = MonitorState.model_validate_json(state.model_dump_json())
    assert restored.sha256 == state.sha256
