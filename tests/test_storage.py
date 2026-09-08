import base64
from datetime import UTC, datetime
from pathlib import Path

from internet_hands.models import ExtractedDocument, FetchResult
from internet_hands.storage import Store, iter_jsonl


def _sample() -> tuple[FetchResult, ExtractedDocument]:
    body = b"<html><body>alpha intelligence beta</body></html>"
    now = datetime.now(UTC)
    result = FetchResult(
        request_url="https://example.com",
        final_url="https://example.com/",
        status_code=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        content_length=len(body),
        sha256="b" * 64,
        elapsed_ms=4.2,
        captured_at=now,
        body_text=body.decode(),
        body_base64=base64.b64encode(body).decode(),
    )
    document = ExtractedDocument(
        url="https://example.com/",
        title="Alpha Page",
        description="Searchable example",
        text="alpha intelligence beta",
        headings=["Alpha"],
        links=["https://example.com/docs"],
        captured_at=now,
        sha256=result.sha256,
    )
    return result, document


def test_store_indexes_searches_and_exports(tmp_path: Path):
    store = Store(tmp_path / "ih.db", tmp_path / "objects")
    result, document = _sample()
    capture_id = store.save_fetch(result, document)
    assert capture_id == 1
    hits = store.search("intelligence")
    assert len(hits) == 1
    assert hits[0].title == "Alpha Page"

    output = tmp_path / "export.jsonl"
    assert store.export_jsonl(output) == 1
    rows = list(iter_jsonl(output))
    assert rows[0]["url"] == "https://example.com/"
    assert rows[0]["headings"] == ["Alpha"]
    object_path = tmp_path / "objects" / "bb" / ("b" * 64)
    assert object_path.read_bytes() == base64.b64decode(result.body_base64)


def test_watch_jobs_are_due_immediately(tmp_path: Path):
    store = Store(tmp_path / "ih.db", tmp_path / "objects")
    job = store.add_watch("https://example.com", 60)
    due = store.due_watches()
    assert [item.id for item in due] == [job.id]
