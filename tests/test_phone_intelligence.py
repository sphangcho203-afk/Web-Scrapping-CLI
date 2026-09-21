from __future__ import annotations

import pytest

from internet_hands.capability_packs import build_default_capabilities
from internet_hands.phone_intelligence import (
    PhoneIntelligenceProvider,
    _safe_external_record,
    local_phone_intelligence,
)


def test_local_phone_intelligence_works_without_external_keys() -> None:
    result = local_phone_intelligence("+14155552671")
    assert result["formats"]["e164"] == "+14155552671"
    assert result["number"]["country_code"] == 1
    assert result["number"]["possible"] is True
    assert result["number"]["valid"] is True
    assert result["line_type"] in {"mobile", "fixed_line", "fixed_line_or_mobile"}
    assert isinstance(result["timezones"], list)


def test_external_filter_drops_subscriber_identity_fields() -> None:
    filtered = _safe_external_record(
        "example",
        {
            "valid": True,
            "carrier": "Example Telecom",
            "line_type": "mobile",
            "subscriber_name": "Private Person",
            "caller_name": "Private Person",
            "address": "Private Address",
            "sim_swap": {"last_sim_swap": {"timestamp": "2026-01-01T00:00:00Z"}},
        },
    )
    assert filtered["carrier"] == "Example Telecom"
    assert "subscriber_name" not in filtered
    assert "caller_name" not in filtered
    assert "address" not in filtered


@pytest.mark.asyncio
async def test_phone_provider_is_always_callable_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "VERIPHONE_API_KEY",
        "ABSTRACT_PHONE_API_KEY",
        "NUMVERIFY_API_KEY",
        "APILAYER_API_KEY",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_API_KEY",
        "TWILIO_API_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    provider = PhoneIntelligenceProvider()
    status = await provider.status()
    descriptor = await provider.describe("lookup")
    result = await provider.execute(
        "lookup",
        {"number": "+14155552671", "external": False},
    )

    assert status["executable"] is True
    assert status["local_provider"] == "libphonenumber"
    assert descriptor.ref == "phoneintel:lookup"
    assert descriptor.metadata["subscriber_identity"] is False
    assert result["status"] == "completed"
    assert result["data"]["policy"]["subscriber_identity"] is False


def test_default_capabilities_include_phone_lookup() -> None:
    capabilities = {item.id: item for item in build_default_capabilities()}
    capability = capabilities["phone.number.lookup"]
    assert capability.pack == "phone"
    assert capability.read_only is True
    assert capability.candidates[0].provider == "phoneintel"
    assert capability.candidates[0].ref == "phoneintel:lookup"
