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



@pytest.mark.asyncio
async def test_brave_llm_context_uses_documented_post_shape_and_server_key(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-test-key")
    calls = []

    async def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return {"grounding": {"generic": []}}

    monkeypatch.setattr(web_search, "_request_json", fake_request)
    result = await web_search.brave_llm_context(
        "how do agent tool routers work",
        count=999,
        maximum_number_of_urls=999,
        maximum_number_of_tokens=999999,
        maximum_number_of_snippets=999,
        maximum_number_of_tokens_per_url=99999,
        maximum_number_of_snippets_per_url=999,
        context_threshold_mode="strict",
        country="in",
        language="en",
    )

    assert result["provider"] == "brave"
    assert result["capability"] == "llm-context"
    method, url, kwargs = calls[0]
    assert method == "POST"
    assert url == "https://api.search.brave.com/res/v1/llm/context"
    assert kwargs["headers"]["X-Subscription-Token"] == "brave-test-key"
    body = kwargs["json_body"]
    assert body["count"] == 50
    assert body["maximum_number_of_urls"] == 50
    assert body["maximum_number_of_tokens"] == 32768
    assert body["maximum_number_of_snippets"] == 256
    assert body["maximum_number_of_tokens_per_url"] == 8192
    assert body["maximum_number_of_snippets_per_url"] == 100
    assert body["context_threshold_mode"] == "strict"
    assert body["safesearch"] == "strict"
    assert body["country"] == "IN"


@pytest.mark.asyncio
async def test_brave_llm_context_rejects_invalid_threshold(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-test-key")
    with pytest.raises(ValueError, match="context_threshold_mode"):
        await web_search.brave_llm_context("query", context_threshold_mode="anything")
