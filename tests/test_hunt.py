import pytest

from internet_hands.hunt import (
    HuntScope,
    _collect_search_urls,
    _same_scope,
    canonicalize_url,
)


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
