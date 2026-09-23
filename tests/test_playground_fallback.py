from internet_hands.playground_api import _needs_fallback

def test_fallback_for_error_or_thin_content():
    assert _needs_fallback({"error":"blocked","text":""})
    assert _needs_fallback({"text":"short"})

def test_no_fallback_for_substantial_native_evidence():
    assert not _needs_fallback({"text":"useful evidence " * 30, "error":None})
