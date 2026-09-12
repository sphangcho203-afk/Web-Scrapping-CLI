import pytest

from internet_hands import web_search
from internet_hands.web_search import SearchKind


@pytest.mark.asyncio
async def test_brave_web_search_uses_strict_safe_search(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-test-key")
    calls = []

    async def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return {"web": {"results": []}}

    monkeypatch.setattr(web_search, "_request_json", fake_request)
    result = await web_search.brave_search(
        "open source web crawlers",
        kind=SearchKind.WEB,
        count=7,
        country="in",
        language="en",
        freshness="pw",
    )

    assert result["provider"] == "brave"
    assert result["data"]["safe_search"] == "strict"
    method, url, kwargs = calls[0]
    assert method == "GET"
    assert url == "https://api.search.brave.com/res/v1/web/search"
    assert kwargs["headers"]["X-Subscription-Token"] == "brave-test-key"
    assert kwargs["params"]["count"] == 7
    assert kwargs["params"]["country"] == "IN"
    assert kwargs["params"]["safesearch"] == "strict"


@pytest.mark.asyncio
async def test_brave_search_caps_result_count(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-test-key")
    calls = []

    async def fake_request(method, url, **kwargs):
        calls.append(kwargs)
        return {"results": []}

    monkeypatch.setattr(web_search, "_request_json", fake_request)
    await web_search.brave_search("cats", kind=SearchKind.VIDEOS, count=999)
    assert calls[0]["params"]["count"] == 20
    assert "freshness" not in calls[0]["params"]
