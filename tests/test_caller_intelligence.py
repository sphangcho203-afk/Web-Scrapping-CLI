from __future__ import annotations

import pytest

from internet_hands.caller_intelligence import (
    CallerIntelligenceProvider,
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
