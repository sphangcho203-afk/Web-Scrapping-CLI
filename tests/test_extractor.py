from datetime import UTC, datetime

from internet_hands.extractor import extract_document
from internet_hands.models import FetchResult


def test_extract_document_collects_structured_html():
    html = """
    <html><head><title>Example Page</title>
    <meta name="description" content="A useful test page"></head>
    <body><h1>Hello World</h1><p>Readable content here.</p>
    <a href="/docs#top">Docs</a><script>ignore me</script></body></html>
    """
    result = FetchResult(
        request_url="https://example.com",
        final_url="https://example.com/",
        status_code=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        content_length=len(html),
        sha256="a" * 64,
        elapsed_ms=1.0,
        captured_at=datetime.now(UTC),
        body_text=html,
    )
    document = extract_document(result)
    assert document.title == "Example Page"
    assert document.description == "A useful test page"
    assert document.headings == ["Hello World"]
    assert "Readable content here." in document.text
    assert "ignore me" not in document.text
    assert document.links == ["https://example.com/docs"]
