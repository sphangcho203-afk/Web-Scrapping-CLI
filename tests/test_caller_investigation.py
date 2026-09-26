from __future__ import annotations

from types import SimpleNamespace

import pytest

from internet_hands.caller_investigation import (
    CallerInvestigationProvider,
    _select_evidence,
    investigate_caller,
)


def test_source_selection_prefers_independent_domains() -> None:
    evidence = [
        {"url": "https://a.example/1", "host": "a.example"},
        {"url": "https://a.example/2", "host": "a.example"},
        {"url": "https://b.example/1", "host": "b.example"},
        {"url": "https://c.example/1", "host": "c.example"},
    ]
    selected = _select_evidence(evidence, max_sources=3)
    assert [item["host"] for item in selected] == [
        "a.example",
        "b.example",
        "c.example",
    ]


@pytest.mark.asyncio
async def test_investigation_corroborates_public_association_without_raw_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_lookup(*args, **kwargs):
        del args, kwargs
        return {
            "number": {
                "formats": {"e164": "+14155552671"},
                "number": {"national_number": "4155552671"},
            },
            "public_attribution": {
                "evidence": [
                    {
                        "title": "Alice Example - Founder | LinkedIn",
                        "url": "https://linkedin.com/in/alice-example",
                        "host": "linkedin.com",
                        "source_kind": "professional_platform",
                    },
                    {
                        "title": "Alice Example - Example Labs",
                        "url": "https://examplelabs.com/contact",
                        "host": "examplelabs.com",
                        "source_kind": "public_web",
                    },
                    {
                        "title": "Phone directory",
                        "url": "https://directory.example/record",
                        "host": "directory.example",
                        "source_kind": "directory_or_listing",
                    },
                ]
            },
        }

    async def fake_fetch(url: str, **kwargs):
        del kwargs
        if "directory.example" in url:
            raise RuntimeError("blocked")
        body = (
            "Public contact: +1 (415) 555-2671. "
            "Private-looking text that must not escape: 42 Example Street."
        )
        return SimpleNamespace(body_text=body, status_code=200)

    monkeypatch.setattr(
        "internet_hands.caller_investigation.lookup_caller_intelligence",
        fake_lookup,
    )
    monkeypatch.setattr(
        "internet_hands.caller_investigation.fetch_url",
        fake_fetch,
    )

    result = await investigate_caller(
        "+14155552671",
        max_sources=3,
    )

    investigation = result["investigation"]
    assert investigation["status"] == "corroborated_public_association"
    assert investigation["confidence"] == "high"
    assert investigation["corroborated_sources"] == 2
    assert investigation["independent_corroborated_domains"] == 2
    assert investigation["public_associations"][0]["label"] == "Alice Example"
    assert investigation["public_associations"][0]["independent_domains"] == 2
    assert "42 Example Street" not in str(result)
    assert result["policy"]["raw_page_content_returned"] is False
    assert result["policy"]["private_address"] is False
    assert result["policy"]["secrets"] is False


@pytest.mark.asyncio
async def test_investigation_does_not_claim_search_only_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_lookup(*args, **kwargs):
        del args, kwargs
        return {
            "number": {
                "formats": {"e164": "+14155552671"},
                "number": {"national_number": "4155552671"},
            },
            "public_attribution": {
                "evidence": [
                    {
                        "title": "Alice Example - Founder | LinkedIn",
                        "url": "https://linkedin.com/in/alice-example",
                        "host": "linkedin.com",
                        "source_kind": "professional_platform",
                    }
                ]
            },
        }

    async def fake_fetch(url: str, **kwargs):
        del url, kwargs
        return SimpleNamespace(
            body_text="This page does not contain the target number.",
            status_code=200,
        )

    monkeypatch.setattr(
        "internet_hands.caller_investigation.lookup_caller_intelligence",
        fake_lookup,
    )
    monkeypatch.setattr(
        "internet_hands.caller_investigation.fetch_url",
        fake_fetch,
    )

    result = await investigate_caller("+14155552671", max_sources=1)
    investigation = result["investigation"]
    assert investigation["status"] == "no_corroborated_public_association"
    assert investigation["confidence"] == "none"
    assert investigation["public_associations"] == []
    assert investigation["evidence"][0]["public_label"] is None


@pytest.mark.asyncio
async def test_caller_investigation_provider_contract() -> None:
    provider = CallerInvestigationProvider()
    status = await provider.status()
    descriptor = await provider.describe("investigate")

    assert status["executable"] is True
    assert status["fetch_backend"] == "native-public-http"
    assert descriptor.ref == "callerresearch:investigate"
    assert descriptor.metadata["private_subscriber_identity"] is False
    assert descriptor.side_effecting is False
