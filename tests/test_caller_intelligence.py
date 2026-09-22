from __future__ import annotations

import pytest

from internet_hands.caller_intelligence import (
    CallerIntelligenceProvider,
    investigate_caller_public_association,
    lookup_caller_intelligence,
)


@pytest.mark.asyncio
async def test_caller_lookup_returns_bounded_public_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

    async def fake_search(*args, **kwargs):
        del args, kwargs
        return {
            "data": {
                "response": {
                    "web": {
                        "results": [
                            {
                                "title": "Example Person - LinkedIn",
                                "url": "https://www.linkedin.com/in/example-person",
                                "description": "123 Private Road should never be emitted here",
                            },
                            {
                                "title": "Example Consulting | Contact",
                                "url": "https://example.com/contact",
                                "description": "Another private-looking address",
                            },
                        ]
                    }
                }
            }
        }

    monkeypatch.setattr(
        "internet_hands.caller_intelligence.brave_search",
        fake_search,
    )

    result = await lookup_caller_intelligence(
        "+14155552671",
        public_search=True,
        max_results=8,
    )

    attribution = result["public_attribution"]
    assert attribution["status"] == "public_evidence_found"
    assert attribution["independent_domains"] == 2
    assert attribution["footprint_strength"] == "multiple_sources"
    assert len(attribution["evidence"]) == 2
    assert attribution["evidence"][0]["source_kind"] == "professional_platform"
    assert "description" not in attribution["evidence"][0]
    assert "Private Road" not in str(result)
    assert result["policy"]["private_address"] is False
    assert result["policy"]["secrets"] is False


@pytest.mark.asyncio
async def test_caller_lookup_degrades_when_public_search_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    result = await lookup_caller_intelligence(
        "+14155552671",
        public_search=True,
    )
    assert result["public_attribution"]["status"] == "unavailable"
    assert result["public_attribution"]["evidence"] == []


@pytest.mark.asyncio
async def test_caller_provider_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    provider = CallerIntelligenceProvider()
    status = await provider.status()
    descriptor = await provider.describe("lookup")
    result = await provider.execute(
        "lookup",
        {
            "number": "+14155552671",
            "public_search": False,
        },
    )

    assert status["executable"] is True
    assert descriptor.ref == "callerintel:lookup"
    assert descriptor.metadata["private_subscriber_identity"] is False
    assert result["status"] == "completed"
    assert result["data"]["public_attribution"]["status"] == "disabled"


class _Fetched:
    def __init__(self, url: str, body: str):
        from datetime import UTC, datetime

        self.final_url = url
        self.status_code = 200
        self.content_type = "text/html"
        self.body_text = body
        self.sha256 = "abc123"
        self.captured_at = datetime.now(UTC)


@pytest.mark.asyncio
async def test_caller_investigation_confirms_number_on_public_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

    async def fake_search(*args, **kwargs):
        del args, kwargs
        return {
            "data": {
                "response": {
                    "web": {
                        "results": [
                            {
                                "title": "Example Person - LinkedIn",
                                "url": "https://linkedin.com/in/example",
                            },
                            {
                                "title": "Example Consulting Contact",
                                "url": "https://example.com/contact",
                            },
                            {
                                "title": "Duplicate host",
                                "url": "https://example.com/other",
                            },
                        ]
                    }
                }
            }
        }

    async def fake_fetch(url: str, **kwargs):
        del kwargs
        return _Fetched(
            url,
            "<html><body>Public contact: +1 (415) 555-2671</body></html>",
        )

    monkeypatch.setattr("internet_hands.caller_intelligence.brave_search", fake_search)
    monkeypatch.setattr("internet_hands.caller_intelligence.fetch_url", fake_fetch)

    result = await investigate_caller_public_association(
        "+14155552671",
        max_search_results=10,
        max_pages=4,
    )

    assert result["discovery"]["selected_pages"] == 2
    assert result["corroboration"]["confirmed_pages"] == 2
    assert result["corroboration"]["independent_confirmed_domains"] == 2
    assert result["corroboration"]["confidence"] == "high"
    assert result["policy"]["raw_page_body_returned"] is False
    assert "body_text" not in str(result)


@pytest.mark.asyncio
async def test_caller_investigation_does_not_confirm_page_without_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

    async def fake_search(*args, **kwargs):
        del args, kwargs
        return {
            "data": {
                "response": {
                    "web": {
                        "results": [
                            {
                                "title": "Unrelated profile",
                                "url": "https://example.com/profile",
                            }
                        ]
                    }
                }
            }
        }

    async def fake_fetch(url: str, **kwargs):
        del kwargs
        return _Fetched(url, "<html><body>No phone number here.</body></html>")

    monkeypatch.setattr("internet_hands.caller_intelligence.brave_search", fake_search)
    monkeypatch.setattr("internet_hands.caller_intelligence.fetch_url", fake_fetch)

    result = await investigate_caller_public_association("+14155552671")
    assert result["corroboration"]["confidence"] == "none"
    assert result["pages"][0]["number_confirmed"] is False


@pytest.mark.asyncio
async def test_caller_provider_exposes_lookup_and_investigate() -> None:
    provider = CallerIntelligenceProvider()
    status = await provider.status()
    lookup = await provider.describe("lookup")
    investigate = await provider.describe("investigate")

    assert status["tool_count"] == 2
    assert lookup.ref == "callerintel:lookup"
    assert investigate.ref == "callerintel:investigate"
    assert investigate.metadata["raw_page_body_returned"] is False
