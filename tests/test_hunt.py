from datetime import UTC, datetime

import pytest

from internet_hands.hunt import (
    HuntScope,
    _collect_search_urls,
    _same_scope,
    _should_render,
    canonicalize_url,
)
from internet_hands.models import ExtractedDocument, FetchResult


def test_canonicalize_url_removes_tracking_and_fragment():
    value = canonicalize_url(
        "HTTPS://Example.COM:443/path?utm_source=x&b=2&a=1&fbclid=dead#section"
    )
    assert value == "https://example.com/path?a=1&b=2"


def test_canonicalize_url_rejects_embedded_credentials():
    with pytest.raises(ValueError, match="Credentials"):
        canonicalize_url("https://user:pass@example.com/private")


def test_scope_modes():
    seed = "https://example.com/a"
    assert _same_scope(seed, "https://example.com/b", HuntScope.ORIGIN)
    assert not _same_scope(seed, "http://example.com/b", HuntScope.ORIGIN)
    assert _same_scope(seed, "http://example.com/b", HuntScope.HOST)
    assert not _same_scope(seed, "https://other.example/b", HuntScope.HOST)
    assert _same_scope(seed, "https://other.example/b", HuntScope.WEB)


def test_collect_search_urls_is_nested_deduplicated_and_bounded():
    payload = {
        "web": {
            "results": [
                {"url": "https://example.com/a?utm_source=x"},
                {"url": "https://example.com/a"},
                {"url": "https://example.org/b"},
            ]
        }
    }
    assert _collect_search_urls(payload, limit=2) == [
        "https://example.com/a",
        "https://example.org/b",
    ]


def test_browser_fallback_only_targets_thin_dynamic_html():
    now = datetime.now(UTC)
    result = FetchResult(
        request_url="https://example.com",
        final_url="https://example.com/",
        status_code=200,
        headers={},
        content_type="text/html",
        content_length=50,
        sha256="a" * 64,
        elapsed_ms=1,
        captured_at=now,
        body_text='<html><body><div id="root"></div><script src="app.js"></script></body></html>',
    )
    thin = ExtractedDocument(
        url=result.final_url,
        text="",
        captured_at=now,
        sha256=result.sha256,
    )
    assert _should_render(result, thin, text_threshold=200)

    rich = thin.model_copy(update={"text": "x" * 500})
    assert not _should_render(result, rich, text_threshold=200)

    error_result = result.model_copy(update={"status_code": 404})
    assert not _should_render(error_result, thin, text_threshold=200)
