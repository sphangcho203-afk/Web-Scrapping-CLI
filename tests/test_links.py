from datetime import UTC, datetime

from internet_hands.fetcher import extract_links
from internet_hands.models import FetchResult


def test_extract_links_normalizes_and_deduplicates():
    result = FetchResult(
        request_url="https://example.com/a",
        final_url="https://example.com/a",
        status_code=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        content_length=1,
        sha256="a" * 64,
        elapsed_ms=1.0,
        captured_at=datetime.now(UTC),
        body_text='<a href="/x#one">x</a><a href="https://example.com/x#two">x2</a>',
    )
    assert extract_links(result).links == ["https://example.com/x"]
