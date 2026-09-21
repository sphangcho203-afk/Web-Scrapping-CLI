from __future__ import annotations

import pytest

from internet_hands.phone_identity import (
    TwilioVerifyProvider,
    VonageVerifyProvider,
    mask_phone,
    normalize_phone,
    select_verification_provider,
)


def test_phone_normalization_uses_e164_and_number_type() -> None:
    value = normalize_phone("+14155552671")
    assert value.e164 == "+14155552671"
    assert value.country_code == 1
    assert value.valid is True
    assert value.possible is True
    assert value.number_type in {"mobile", "fixed_line", "fixed_line_or_mobile"}


def test_phone_normalization_rejects_invalid_numbers() -> None:
    with pytest.raises(ValueError):
        normalize_phone("+100")


def test_phone_mask_does_not_expose_full_number() -> None:
    masked = mask_phone("+14155552671")
    assert masked.startswith("+14")
    assert masked.endswith("2671")
    assert "555" not in masked


@pytest.mark.asyncio
async def test_twilio_verify_start_and_check(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = TwilioVerifyProvider()
    provider.service_sid = "VA123"
    provider.account_sid = "AC123"
    provider.auth_token = "secret"

    calls: list[tuple[str, dict[str, str]]] = []

    async def fake_post(path: str, data: dict[str, str]):
        calls.append((path, data))
        if path.endswith("/VerificationCheck"):
            return {"sid": "VE123", "status": "approved", "valid": True}
        return {"sid": "VE123", "status": "pending", "send_code_attempts": []}

    monkeypatch.setattr(provider, "_post", fake_post)
    started = await provider.start("+14155552671", channel="sms")
    checked = await provider.check("+14155552671", started.request_id, "123456")

    assert started.request_id == "VE123"
    assert checked.approved is True
    assert calls[0][1] == {"To": "+14155552671", "Channel": "sms"}
    assert calls[1][1]["Code"] == "123456"


@pytest.mark.asyncio
async def test_vonage_verify_uses_provider_generated_code(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = VonageVerifyProvider()
    provider.api_key = "key"
    provider.api_secret = "secret"
    provider.brand = "Internet Hands"

    calls: list[tuple[str, str, dict | None]] = []

    async def fake_request(method: str, path: str, *, json=None):
        calls.append((method, path, json))
        if path == "/":
            return {"request_id": "req_1"}
        return {"request_id": "req_1", "status": "completed"}

    monkeypatch.setattr(provider, "_request", fake_request)
    started = await provider.start("+447700900000", channel="sms")
    checked = await provider.check("+447700900000", started.request_id, "123456")

    assert started.request_id == "req_1"
    assert checked.approved is True
    assert "code" not in calls[0][2]
    assert calls[0][2]["workflow"][0]["to"] == "447700900000"


def test_provider_selection_falls_back_only_before_send(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_API_KEY", raising=False)
    monkeypatch.delenv("TWILIO_API_SECRET", raising=False)
    monkeypatch.delenv("TWILIO_VERIFY_SERVICE_SID", raising=False)
    monkeypatch.setenv("VONAGE_API_KEY", "key")
    monkeypatch.setenv("VONAGE_API_SECRET", "secret")
    monkeypatch.setenv("VONAGE_VERIFY_BRAND", "Internet Hands")
    monkeypatch.setenv("PHONE_VERIFY_PROVIDERS", "twilio,vonage")

    provider = select_verification_provider()
    assert provider.name == "vonage"
