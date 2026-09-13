from datetime import UTC, datetime

from internet_hands.models import FetchResult
from internet_hands.object_store import LocalObjectStore, capture_bytes


def _result() -> FetchResult:
    return FetchResult(
        request_url="https://example.com/",
        final_url="https://example.com/",
        status_code=200,
        headers={"content-type": "text/plain"},
        content_type="text/plain",
        content_length=5,
        sha256="2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        elapsed_ms=1.0,
        captured_at=datetime.now(UTC),
        body_text="hello",
    )


def test_local_object_store_is_content_addressed(tmp_path):
    store = LocalObjectStore(tmp_path / "objects")
    result = _result()

    first = store.put_capture(result)
    second = store.put_capture(result)

    assert first == second
    assert first is not None
    assert store.get(first) == b"hello"
    assert first.endswith(result.sha256)


def test_capture_bytes_handles_empty_capture_body():
    result = _result().model_copy(update={"body_text": None, "body_base64": None})
    assert capture_bytes(result) is None
