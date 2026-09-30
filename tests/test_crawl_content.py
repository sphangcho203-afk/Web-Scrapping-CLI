from datetime import UTC, datetime
from urllib.robotparser import RobotFileParser

import pytest

from internet_hands import crawler
from internet_hands.models import FetchResult

CAPTURED = datetime(2026, 9, 29, tzinfo=UTC)


@pytest.fixture
def capture_site(monkeypatch):
    calls = []
    bodies = {
        "https://example.com/": '<html><head><title>API guide</title><meta name="description" content="Documentation"></head><body><h1>Getting started</h1><p>Create your key.</p><script>SECRET_SCRIPT</script><a href="/pricing">Pricing</a></body></html>',
        "https://example.com/pricing": '<html><head><title>Pricing</title></head><body><p>Monthly plan costs $20.</p></body></html>',
    }
    statuses = {}

    async def fetch(url, **kwargs):
        calls.append(url)
        return FetchResult(request_url=url, final_url=url, status_code=statuses.get(url, 200),
                           headers={}, content_type="text/html", content_length=len(bodies[url].encode()),
                           sha256="a" * 64, elapsed_ms=1, captured_at=CAPTURED, body_text=bodies[url])

    async def robots(url):
        parser = RobotFileParser()
        parser.parse(["User-agent: *", "Allow: /"])
        return parser

    monkeypatch.setattr(crawler, "fetch_url", fetch)
    monkeypatch.setattr(crawler, "validate_public_http_url", lambda _: None)
    monkeypatch.setattr(crawler, "_robots_for", robots)
    return calls, bodies, statuses


async def test_crawl_content_reuses_capture_and_preserves_provenance(capture_site):
    calls, _, _ = capture_site
    result = await crawler.crawl("https://example.com/", max_pages=2, delay_seconds=0,
                                 include_content=True)
    page = result.pages[0]
    assert page.title == "API guide"
    assert page.description == "Documentation"
    assert "Create your key." in page.text and "SECRET_SCRIPT" not in page.text
    assert page.headings == ["Getting started"]
    assert page.captured_at == CAPTURED and page.sha256 == "a" * 64
    assert page.content_truncated is False
    assert calls == ["https://example.com/", "https://example.com/pricing"]
    assert "costs $20" in result.pages[1].text


async def test_content_off_keeps_metadata_without_text(capture_site):
    result = await crawler.crawl("https://example.com/", max_pages=1, delay_seconds=0)
    assert result.pages[0].text is None
    assert result.pages[0].status_code == 200 and result.pages[0].links_found == 1


async def test_utf8_per_page_and_aggregate_budget_is_explicit(capture_site):
    _, bodies, _ = capture_site
    bodies["https://example.com/"] = '<html><body>' + 'অসম ' * 2000 + '<a href="/pricing">Next</a></body></html>'
    bodies["https://example.com/pricing"] = '<html><body>' + 'বাংলা ' * 2000 + '</body></html>'
    result = await crawler.crawl("https://example.com/", max_pages=2, delay_seconds=0,
                                 include_content=True, max_content_bytes_per_page=4000,
                                 max_content_bytes=5000)
    assert len(result.pages[0].text.encode()) <= 4000
    assert sum(len((page.text or "").encode()) for page in result.pages) <= 5000
    assert all(page.content_truncated for page in result.pages)
    assert result.content_truncated is True
    assert "\ufffd" not in result.pages[0].text


async def test_error_response_is_not_extracted_as_page_content(capture_site):
    _, _, statuses = capture_site
    statuses["https://example.com/"] = 403
    result = await crawler.crawl("https://example.com/", max_pages=1, delay_seconds=0,
                                 include_content=True)
    assert result.pages[0].status_code == 403
    assert result.pages[0].text is None


async def test_robots_denial_never_fetches_or_extracts(capture_site, monkeypatch):
    calls, _, _ = capture_site
    async def robots(url):
        parser = RobotFileParser()
        parser.parse(["User-agent: *", "Disallow: /"])
        return parser
    monkeypatch.setattr(crawler, "_robots_for", robots)
    result = await crawler.crawl("https://example.com/", include_content=True)
    assert calls == [] and result.pages[0].text is None
    assert result.pages[0].error == "blocked by robots.txt"


@pytest.mark.parametrize("options", [
    {"max_content_bytes_per_page": 0}, {"max_content_bytes_per_page": 200_001},
    {"max_content_bytes": 0}, {"max_content_bytes": 1_000_001},
])
async def test_invalid_content_budgets_reject_before_fetch(capture_site, options):
    calls, _, _ = capture_site
    with pytest.raises(ValueError, match="content"):
        await crawler.crawl("https://example.com/", include_content=True, **options)
    assert calls == []


async def test_concurrent_pages_share_text_budget(capture_site):
    _, bodies, _ = capture_site
    bodies["https://example.com/"] = '<a href="/pricing">Pricing</a><a href="/other">Other</a>'
    bodies["https://example.com/pricing"] = '<p>' + 'A' * 200 + '</p>'
    bodies["https://example.com/other"] = '<p>' + 'B' * 200 + '</p>'
    result = await crawler.crawl("https://example.com/", max_pages=3, concurrency=2,
                                 delay_seconds=0, include_content=True, max_content_bytes=100)
    assert len(result.pages) == 3
    assert result.content_bytes == sum(len((page.text or "").encode()) for page in result.pages) == 100
    assert result.content_truncated


async def test_extraction_failure_preserves_fetch(capture_site, monkeypatch):
    def fail(result):
        raise ValueError("broken extraction")
    monkeypatch.setattr(crawler, "extract_document", fail)
    result = await crawler.crawl("https://example.com/", max_pages=1, include_content=True)
    page = result.pages[0]
    assert page.status_code == 200 and page.error is None
    assert page.text is None and "could not be extracted" in page.content_error


async def test_playground_content_reaches_saved_rows_and_exports(capture_site, monkeypatch):
    import json

    from starlette.requests import Request

    from internet_hands import playground_api
    from internet_hands.control_store import AuthIdentity
    from internet_hands.datasets import DatasetStore, export_rows, result_rows

    identity = AuthIdentity(user_id="usr_test", api_key_id="key_test", scopes=["mcp:execute"],
                            plan_slug="free", rpm_limit=10, source="api_key")
    saved = {}
    finished = []

    class Meter:
        def reserve_tool_call(self, **kwargs):
            return 100

        def finish_usage(self, *args, **kwargs):
            finished.append(kwargs)

    def save(self, user_id, request_id, operation, payload, name):
        saved.update(payload)
        return {"id": "ds_content", "row_count": len(result_rows(payload))}

    monkeypatch.setattr(playground_api, "store", Meter())
    monkeypatch.setattr(playground_api, "_playground_identity", lambda request, body: identity)
    monkeypatch.setattr(playground_api, "validate_public_http_url", lambda _: None)
    monkeypatch.setattr(DatasetStore, "save", save)
    body = json.dumps({"operation": "crawl", "url": "https://example.com/", "max_pages": 2,
                       "max_content_bytes_per_page": 25}).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request({"type": "http", "method": "POST", "path": "/api/playground/run", "headers": []}, receive)
    response = await playground_api.playground_run(request)
    assert response["dataset"]["id"] == "ds_content"
    assert saved == response["result"] and saved["pages"][0]["title"] == "API guide"
    assert saved["pages"][0]["content_truncated"]
    assert response["summary"]["content_bytes"] <= 50
    assert finished[0]["status"] == "ok" and response["usage"]["metered"]
    rows = result_rows(saved)
    exported, _ = export_rows(rows, "jsonl")
    page = json.loads(exported.splitlines()[0])
    assert page["record_type"] == "pages" and page["text"] == saved["pages"][0]["text"]
    assert page["captured_at"] == CAPTURED.isoformat().replace("+00:00", "Z")
    csv_output, _ = export_rows(rows, "csv")
    assert "content_truncated" in csv_output and "API guide" in csv_output


@pytest.mark.parametrize("content_type,body,expected_error", [
    ("application/pdf", "binary", "does not support"),
    ("text/html", "<html><body></body></html>", "No readable text"),
])
async def test_unsupported_and_empty_captures_are_explicit(capture_site, monkeypatch, content_type, body, expected_error):
    original_fetch = crawler.fetch_url

    async def fetch(url, **kwargs):
        result = await original_fetch(url, **kwargs)
        return result.model_copy(update={"content_type": content_type, "body_text": body})

    monkeypatch.setattr(crawler, "fetch_url", fetch)
    result = await crawler.crawl("https://example.com/", max_pages=1, include_content=True)
    assert result.pages[0].status_code == 200
    assert expected_error in result.pages[0].content_error
    assert result.content_bytes == 0
