import pytest

from internet_hands import social


@pytest.mark.asyncio
async def test_youtube_search_uses_official_search_endpoint(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    calls = []

    async def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return {"items": [{"id": {"videoId": "abc"}}]}

    monkeypatch.setattr(social, "_request_json", fake_request)
    result = await social.youtube_search("internet hands", limit=7)

    assert result["provider"] == "youtube"
    assert result["capability"] == "search"
    method, url, kwargs = calls[0]
    assert method == "GET"
    assert url == "https://www.googleapis.com/youtube/v3/search"
    assert kwargs["params"]["maxResults"] == 7
    assert kwargs["params"]["key"] == "test-key"


@pytest.mark.asyncio
async def test_tiktok_video_list_is_authorized_and_bounded(monkeypatch):
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "token-value")
    calls = []

    async def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return {"data": {"videos": []}}

    monkeypatch.setattr(social, "_request_json", fake_request)
    result = await social.tiktok_authorized_videos(limit=999)

    assert result["provenance"]["public_data"] is False
    method, url, kwargs = calls[0]
    assert method == "POST"
    assert url == "https://open.tiktokapis.com/v2/video/list/"
    assert kwargs["json_body"]["max_count"] == 20
    assert kwargs["headers"]["Authorization"] == "Bearer token-value"


@pytest.mark.asyncio
async def test_youtube_comments_paginates_until_limit(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    calls = []

    async def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if len(calls) == 1:
            return {"items": [{"id": "a"}, {"id": "b"}], "nextPageToken": "next"}
        return {"items": [{"id": "c"}]}

    monkeypatch.setattr(social, "_request_json", fake_request)
    result = await social.youtube_comments("https://youtu.be/abc", limit=3)

    assert result["data"]["count"] == 3
    assert [item["id"] for item in result["data"]["items"]] == ["a", "b", "c"]
    assert calls[1][2]["params"]["pageToken"] == "next"
