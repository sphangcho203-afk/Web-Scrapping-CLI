from __future__ import annotations

import base64
import os
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import httpx
import phonenumbers
from phonenumbers import PhoneNumberFormat, PhoneNumberType


class PhoneVerificationError(RuntimeError):
    pass


class PhoneVerificationRejected(PhoneVerificationError):
    """Provider rejected the request before a verification could start."""


class PhoneVerificationTransportError(PhoneVerificationError):
    """Provider outcome may be unknown; do not automatically retry another sender."""


@dataclass(slots=True)
class NormalizedPhone:
    e164: str
    country_code: int
    region_code: str | None
    national_number: str
    number_type: str
    possible: bool
    valid: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class VerificationStart:
    provider: str
    request_id: str
    channel: str
    status: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class VerificationCheck:
    provider: str
    request_id: str
    approved: bool
    status: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PhoneVerificationProvider(Protocol):
    name: str

    def configured(self) -> bool: ...

    async def start(self, phone_e164: str, *, channel: str = "sms") -> VerificationStart: ...

    async def check(
        self, phone_e164: str, request_id: str, code: str
    ) -> VerificationCheck: ...


_NUMBER_TYPES = {
    PhoneNumberType.FIXED_LINE: "fixed_line",
    PhoneNumberType.MOBILE: "mobile",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_line_or_mobile",
    PhoneNumberType.TOLL_FREE: "toll_free",
    PhoneNumberType.PREMIUM_RATE: "premium_rate",
    PhoneNumberType.SHARED_COST: "shared_cost",
    PhoneNumberType.VOIP: "voip",
    PhoneNumberType.PERSONAL_NUMBER: "personal_number",
    PhoneNumberType.PAGER: "pager",
    PhoneNumberType.UAN: "uan",
    PhoneNumberType.VOICEMAIL: "voicemail",
    PhoneNumberType.UNKNOWN: "unknown",
}


def normalize_phone(value: str, *, default_region: str | None = None) -> NormalizedPhone:
    raw = " ".join(str(value or "").split())
    if not raw:
        raise ValueError("phone number is required")
    try:
        parsed = phonenumbers.parse(raw, default_region.upper() if default_region else None)
    except phonenumbers.NumberParseException as exc:
        raise ValueError("phone number could not be parsed") from exc

    possible = phonenumbers.is_possible_number(parsed)
    valid = phonenumbers.is_valid_number(parsed)
    if not possible or not valid:
        raise ValueError("phone number is not valid")

    region = phonenumbers.region_code_for_number(parsed)
    number_type = _NUMBER_TYPES.get(phonenumbers.number_type(parsed), "unknown")
    return NormalizedPhone(
        e164=phonenumbers.format_number(parsed, PhoneNumberFormat.E164),
        country_code=int(parsed.country_code),
        region_code=region or None,
        national_number=str(parsed.national_number),
        number_type=number_type,
        possible=possible,
        valid=valid,
    )


def mask_phone(phone_e164: str) -> str:
    digits = "".join(ch for ch in phone_e164 if ch.isdigit())
    if len(digits) <= 4:
        return "+" + "*" * max(len(digits) - 2, 0) + digits[-2:]
    return f"+{digits[:2]}{'*' * max(len(digits) - 6, 3)}{digits[-4:]}"


class TwilioVerifyProvider:
    name = "twilio"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        self.api_key = os.getenv("TWILIO_API_KEY", "").strip()
        self.api_secret = os.getenv("TWILIO_API_SECRET", "").strip()
        self.service_sid = os.getenv("TWILIO_VERIFY_SERVICE_SID", "").strip()
        self._client = client

    def configured(self) -> bool:
        auth = bool(
            (self.api_key and self.api_secret)
            or (self.account_sid and self.auth_token)
        )
        return bool(auth and self.service_sid)

    def _auth(self) -> tuple[str, str]:
        if self.api_key and self.api_secret:
            return self.api_key, self.api_secret
        if self.account_sid and self.auth_token:
            return self.account_sid, self.auth_token
        raise PhoneVerificationError("Twilio credentials are not configured")

    async def _post(self, path: str, data: dict[str, str]) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=20.0)
        try:
            try:
                response = await client.post(
                    f"https://verify.twilio.com/v2{path}",
                    data=data,
                    auth=self._auth(),
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise PhoneVerificationTransportError(
                    f"Twilio Verify transport failed: {type(exc).__name__}"
                ) from exc
            payload: dict[str, Any]
            try:
                parsed = response.json()
                payload = parsed if isinstance(parsed, dict) else {}
            except ValueError:
                payload = {}
            if response.is_error:
                message = str(
                    payload.get("message")
                    or payload.get("detail")
                    or f"HTTP {response.status_code}"
                )
                # A provider 4xx response means the request was synchronously rejected.
                if 400 <= response.status_code < 500:
                    raise PhoneVerificationRejected(
                        f"Twilio Verify rejected request: {message[:300]}"
                    )
                raise PhoneVerificationTransportError(
                    f"Twilio Verify failed with HTTP {response.status_code}"
                )
            return payload
        finally:
            if owns_client:
                await client.aclose()

    async def start(self, phone_e164: str, *, channel: str = "sms") -> VerificationStart:
        if channel not in {"sms", "call", "whatsapp"}:
            raise ValueError("Twilio channel must be sms, call, or whatsapp")
        payload = await self._post(
            f"/Services/{self.service_sid}/Verifications",
            {"To": phone_e164, "Channel": channel},
        )
        sid = str(payload.get("sid") or "").strip()
        if not sid:
            raise PhoneVerificationTransportError("Twilio Verify did not return a request id")
        return VerificationStart(
            provider=self.name,
            request_id=sid,
            channel=channel,
            status=str(payload.get("status") or "pending"),
            metadata={
                "send_code_attempts": payload.get("send_code_attempts") or [],
                "valid": payload.get("valid"),
            },
        )

    async def check(
        self, phone_e164: str, request_id: str, code: str
    ) -> VerificationCheck:
        del request_id
        payload = await self._post(
            f"/Services/{self.service_sid}/VerificationCheck",
            {"To": phone_e164, "Code": code},
        )
        status = str(payload.get("status") or "")
        approved = status == "approved" or payload.get("valid") is True
        return VerificationCheck(
            provider=self.name,
            request_id=str(payload.get("sid") or ""),
            approved=approved,
            status=status or ("approved" if approved else "pending"),
            metadata={"valid": payload.get("valid")},
        )


class VonageVerifyProvider:
    name = "vonage"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.api_key = os.getenv("VONAGE_API_KEY", "").strip()
        self.api_secret = os.getenv("VONAGE_API_SECRET", "").strip()
        self.brand = (os.getenv("VONAGE_VERIFY_BRAND") or "Internet Hands").strip()[:18]
        self._client = client

    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret and self.brand)

    def _authorization(self) -> str:
        if not self.configured():
            raise PhoneVerificationError("Vonage Verify credentials are not configured")
        raw = f"{self.api_key}:{self.api_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode("ascii")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=20.0)
        try:
            try:
                response = await client.request(
                    method,
                    f"https://api.nexmo.com/v2/verify{path}",
                    json=json,
                    headers={
                        "Authorization": self._authorization(),
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
            except httpx.HTTPError as exc:
                raise PhoneVerificationTransportError(
                    f"Vonage Verify transport failed: {type(exc).__name__}"
                ) from exc
            payload: dict[str, Any]
            try:
                parsed = response.json()
                payload = parsed if isinstance(parsed, dict) else {}
            except ValueError:
                payload = {}
            if response.is_error:
                detail = str(
                    payload.get("detail")
                    or payload.get("title")
                    or payload.get("error")
                    or f"HTTP {response.status_code}"
                )
                if 400 <= response.status_code < 500:
                    raise PhoneVerificationRejected(
                        f"Vonage Verify rejected request: {detail[:300]}"
                    )
                raise PhoneVerificationTransportError(
                    f"Vonage Verify failed with HTTP {response.status_code}"
                )
            return payload
        finally:
            if owns_client:
                await client.aclose()

    async def start(self, phone_e164: str, *, channel: str = "sms") -> VerificationStart:
        if channel not in {"sms", "voice"}:
            raise ValueError("Vonage channel must be sms or voice")
        to = phone_e164.lstrip("+")
        workflow: list[dict[str, Any]] = [{"channel": channel, "to": to}]
        if channel == "sms" and os.getenv("VONAGE_VERIFY_VOICE_FALLBACK", "1") != "0":
            workflow.append({"channel": "voice", "to": to})
        payload = await self._request(
            "POST",
            "/",
            json={
                "brand": self.brand,
                "code_length": 6,
                "fraud_check": True,
                "workflow": workflow,
            },
        )
        request_id = str(payload.get("request_id") or "").strip()
        if not request_id:
            raise PhoneVerificationTransportError("Vonage Verify did not return a request id")
        return VerificationStart(
            provider=self.name,
            request_id=request_id,
            channel=channel,
            status=str(payload.get("status") or "pending"),
            metadata={"workflow": workflow},
        )

    async def check(
        self, phone_e164: str, request_id: str, code: str
    ) -> VerificationCheck:
        del phone_e164
        payload = await self._request(
            "POST",
            f"/{request_id}",
            json={"code": code},
        )
        status = str(payload.get("status") or "")
        approved = status == "completed"
        return VerificationCheck(
            provider=self.name,
            request_id=str(payload.get("request_id") or request_id),
            approved=approved,
            status=status or ("completed" if approved else "pending"),
            metadata={},
        )


def verification_providers() -> list[PhoneVerificationProvider]:
    providers: dict[str, PhoneVerificationProvider] = {
        "twilio": TwilioVerifyProvider(),
        "vonage": VonageVerifyProvider(),
    }
    preferred = [
        item.strip().lower()
        for item in os.getenv("PHONE_VERIFY_PROVIDERS", "twilio,vonage").split(",")
        if item.strip()
    ]
    ordered = [providers[name] for name in preferred if name in providers]
    for name, provider in providers.items():
        if name not in preferred:
            ordered.append(provider)
    return ordered


def select_verification_provider() -> PhoneVerificationProvider:
    for provider in verification_providers():
        if provider.configured():
            return provider
    raise PhoneVerificationError(
        "no phone verification provider is configured; configure Twilio Verify or Vonage Verify"
    )


async def lookup_phone_intelligence(phone_e164: str) -> dict[str, Any]:
    """Return non-identifying telecom intelligence for the account's verified number only."""
    normalized = normalize_phone(phone_e164)
    result: dict[str, Any] = {
        "source": "libphonenumber",
        "phone": normalized.to_dict(),
        "line_type": normalized.number_type,
        "carrier": None,
        "sim_swap": None,
        "provider": None,
    }

    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    api_key = os.getenv("TWILIO_API_KEY", "").strip()
    api_secret = os.getenv("TWILIO_API_SECRET", "").strip()
    if not ((account_sid and auth_token) or (api_key and api_secret)):
        return result

    fields = ["line_type_intelligence"]
    if os.getenv("TWILIO_LOOKUP_SIM_SWAP", "0") == "1":
        fields.append("sim_swap")
    auth = (api_key, api_secret) if api_key and api_secret else (account_sid, auth_token)

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.get(
                f"https://lookups.twilio.com/v2/PhoneNumbers/{phone_e164}",
                params={"Fields": ",".join(fields)},
                auth=auth,
                headers={"Accept": "application/json"},
            )
            if response.is_error:
                result["provider_error"] = f"Twilio Lookup HTTP {response.status_code}"
                return result
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            result["provider_error"] = f"Twilio Lookup unavailable: {type(exc).__name__}"
            return result

    if not isinstance(payload, dict):
        return result

    line = payload.get("line_type_intelligence")
    if isinstance(line, dict):
        result["line_type"] = line.get("type") or result["line_type"]
        result["carrier"] = line.get("carrier_name")
        result["mobile_country_code"] = line.get("mobile_country_code")
        result["mobile_network_code"] = line.get("mobile_network_code")
        result["provider"] = "twilio_lookup"

    sim_swap = payload.get("sim_swap")
    if isinstance(sim_swap, dict):
        # Keep only anti-fraud fields; never expose subscriber-name identity data.
        last_swap = sim_swap.get("last_sim_swap")
        result["sim_swap"] = {
            "last_sim_swap": last_swap if isinstance(last_swap, dict) else None,
            "carrier_name": sim_swap.get("carrier_name"),
            "mobile_country_code": sim_swap.get("mobile_country_code"),
            "mobile_network_code": sim_swap.get("mobile_network_code"),
            "error_code": sim_swap.get("error_code"),
        }
        result["provider"] = "twilio_lookup"

    return result
