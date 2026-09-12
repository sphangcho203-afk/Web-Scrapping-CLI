import pytest

import internet_hands.public_data as public_data


def test_language_validation_blocks_host_injection():
    assert public_data._language("EN") == "en"
    with pytest.raises(ValueError):
        public_data._language("en.example.com")


def test_package_validation_rejects_path_traversal():
    assert public_data._package("@scope/pkg") == "@scope/pkg"
    with pytest.raises(ValueError):
        public_data._package("../secret")


@pytest.mark.asyncio
async def test_wikipedia_search_builds_public_api_request(monkeypatch):
    calls = []

    async def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return {"query": {"search": []}}

    monkeypatch.setattr(public_data, "_request_json", fake_request)
    result = await public_data.wikipedia_search("Ada Lovelace", language="en", limit=5)

    assert result["provider"] == "wikipedia"
    method, url, kwargs = calls[0]
    assert method == "GET"
    assert url == "https://en.wikipedia.org/w/api.php"
    assert kwargs["params"]["srsearch"] == "Ada Lovelace"
    assert kwargs["params"]["srlimit"] == 5


@pytest.mark.asyncio
async def test_npm_scoped_package_is_encoded(monkeypatch):
    calls = []

    async def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return {"name": "@scope/pkg"}

    monkeypatch.setattr(public_data, "_request_json", fake_request)
    result = await public_data.npm_package("@scope/pkg")

    assert result["data"]["name"] == "@scope/pkg"
    assert calls[0][1] == "https://registry.npmjs.org/@scope%2Fpkg"
