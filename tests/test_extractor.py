from datetime import UTC, datetime

from internet_hands import extractor
from internet_hands.extractor import extract_document
from internet_hands.models import FetchResult


def _fetch_result(html: str) -> FetchResult:
    return FetchResult(
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


def test_extract_document_collects_structured_html():
    html = """
    <html><head><title>Example Page</title>
    <meta name="description" content="A useful test page"></head>
    <body><h1>Hello World</h1><p>Readable content here.</p>
    <a href="/docs#top">Docs</a><script>ignore me</script></body></html>
    """
    document = extract_document(_fetch_result(html))
    assert document.title == "Example Page"
    assert document.description == "A useful test page"
    assert document.headings == ["Hello World"]
    assert "Readable content here." in document.text
    assert "ignore me" not in document.text
    assert document.links == ["https://example.com/docs"]


def test_trafilatura_can_enhance_text_without_replacing_native_links(monkeypatch):
    html = """
    <html><head><title>Native title</title></head>
    <body><p>Boilerplate and article text.</p><a href="/source">Source</a></body></html>
    """

    class FakeTrafilatura:
        @staticmethod
        def extract(value, **kwargs):
            assert value == html
            assert kwargs == {"output_format": "json", "with_metadata": True}
            return (
                '{"title":"Enhanced title","description":"Enhanced description",'
                '"text":"Clean article text."}'
            )

    monkeypatch.setattr(extractor, "_load_trafilatura", lambda: FakeTrafilatura)

    document = extract_document(_fetch_result(html))
    assert document.title == "Enhanced title"
    assert document.description == "Enhanced description"
    assert document.text == "Clean article text."
    assert document.links == ["https://example.com/source"]
