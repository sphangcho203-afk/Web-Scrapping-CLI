from datetime import UTC, datetime

from internet_hands.exports import export_warc
from internet_hands.models import ExtractedDocument, FetchResult
from internet_hands.storage import Store


def test_export_warc_contains_response_and_body(tmp_path):
    now = datetime.now(UTC)
    body = "<html><body>Hello archive</body></html>"
    result = FetchResult(
        request_url="https://example.com/",
        final_url="https://example.com/",
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8", "x-test": "yes"},
        content_type="text/html; charset=utf-8",
        content_length=len(body.encode("utf-8")),
        sha256="a" * 64,
        elapsed_ms=12.5,
        captured_at=now,
        body_text=body,
    )
    document = ExtractedDocument(
        url="https://example.com/",
        title="Example",
        description=None,
        text="Hello archive",
        headings=[],
        links=[],
        captured_at=now,
        sha256="a" * 64,
    )
    db = tmp_path / "data.db"
    Store(db, tmp_path / "objects").save_fetch(result, document)

    target = tmp_path / "captures.warc"
    assert export_warc(db, target) == 1
    payload = target.read_bytes()
    assert b"WARC/1.1" in payload
    assert b"WARC-Type: response" in payload
    assert b"WARC-Target-URI: https://example.com/" in payload
    assert b"HTTP/1.1 200 OK" in payload
    assert b"Hello archive" in payload
