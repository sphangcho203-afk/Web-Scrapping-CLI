from internet_hands.playground_api import _canonical_source_url

def test_canonical_source_url_drops_query_fragment_and_trailing_slash():
    assert _canonical_source_url("HTTPS://Example.COM/docs/?utm_source=x#top") == "https://example.com/docs"

def test_canonical_source_url_preserves_root():
    assert _canonical_source_url("https://example.com") == "https://example.com/"
