from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import httpx
import phonenumbers
from phonenumbers import PhoneNumberFormat, PhoneNumberType, carrier, geocoder, timezone


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


class SmsGateVerifyProvider:
    """Self-hosted OTP transport using SMS Gateway for Android-compatible REST APIs."""

    name = "smsgate"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.send_url = os.getenv("SMSGATE_SEND_URL", "").strip()
        self.username = os.getenv("SMSGATE_USERNAME", "").strip()
        self.password = os.getenv("SMSGATE_PASSWORD", "").strip()
        self.signing_secret = (
            os.getenv("INTERNET_HANDS_OTP_SIGNING_SECRET", "").strip()
            or os.getenv("INTERNET_HANDS_ENCRYPTION_KEY", "").strip()
        )
        self._client = client

    def configured(self) -> bool:
        return bool(
            self.send_url
            and self.username
            and self.password
            and self.signing_secret
        )

    def _proof(self, phone_e164: str, code: str, expires_at: int, nonce: str) -> str:
        message = f"{phone_e164}|{code}|{expires_at}|{nonce}".encode("utf-8")
        return hmac.new(
            self.signing_secret.encode("utf-8"),
            message,
            hashlib.sha256,
        ).hexdigest()

    async def start(self, phone_e164: str, *, channel: str = "sms") -> VerificationStart:
        if channel != "sms":
            raise ValueError("self-hosted SMS gateway verification supports SMS only")
        if not self.configured():
            raise PhoneVerificationError("self-hosted SMS gateway is not configured")

        digits = max(4, min(int(os.getenv("SMSGATE_OTP_LENGTH", "6")), 9))
        code = f"{secrets.randbelow(10**digits):0{digits}d}"
        ttl = max(60, min(int(os.getenv("SMSGATE_OTP_TTL_SECONDS", "600")), 1800))
        expires_at = int(time.time()) + ttl
        nonce = secrets.token_urlsafe(12)
        proof = self._proof(phone_e164, code, expires_at, nonce)
        request_id = f"{expires_at}.{nonce}.{proof}"
        template = os.getenv(
            "SMSGATE_OTP_MESSAGE",
            "Your Internet Hands verification code is {code}. It expires shortly.",
        )
        message = template.replace("{code}", code)

        payload: dict[str, Any] = {
            "textMessage": {"text": message},
            "phoneNumbers": [phone_e164],
        }
        device_id = os.getenv("SMSGATE_DEVICE_ID", "").strip()
        if device_id:
            payload["deviceId"] = device_id
        sim_number = os.getenv("SMSGATE_SIM_NUMBER", "").strip()
        if sim_number:
            try:
                payload["simNumber"] = int(sim_number)
            except ValueError as exc:
                raise PhoneVerificationError("SMSGATE_SIM_NUMBER must be an integer") from exc

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=20.0)
        try:
            try:
                response = await client.post(
                    self.send_url,
                    json=payload,
                    auth=(self.username, self.password),
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise PhoneVerificationTransportError(
                    f"self-hosted SMS gateway transport failed: {type(exc).__name__}"
                ) from exc
            if response.is_error:
                if 400 <= response.status_code < 500:
                    raise PhoneVerificationRejected(
                        f"self-hosted SMS gateway rejected request: HTTP {response.status_code}"
                    )
                raise PhoneVerificationTransportError(
                    f"self-hosted SMS gateway failed with HTTP {response.status_code}"
                )
        finally:
            if owns_client:
                await client.aclose()

        return VerificationStart(
            provider=self.name,
            request_id=request_id,
            channel="sms",
            status="pending",
            metadata={"expires_in": ttl, "transport": "android_sms_gateway"},
        )

    async def check(
        self, phone_e164: str, request_id: str, code: str
    ) -> VerificationCheck:
        try:
            expiry_raw, nonce, expected = request_id.split(".", 2)
            expires_at = int(expiry_raw)
        except (TypeError, ValueError) as exc:
            raise PhoneVerificationRejected("self-hosted OTP challenge is invalid") from exc
        if int(time.time()) > expires_at:
            return VerificationCheck(
                provider=self.name,
                request_id=request_id,
                approved=False,
                status="expired",
                metadata={},
            )
        actual = self._proof(phone_e164, code, expires_at, nonce)
        approved = hmac.compare_digest(actual, expected)
        return VerificationCheck(
            provider=self.name,
            request_id=request_id,
            approved=approved,
            status="approved" if approved else "pending",
            metadata={"transport": "android_sms_gateway"},
        )


class Msg91VerifyProvider:
    name = "msg91"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.auth_key = os.getenv("MSG91_AUTH_KEY", "").strip()
        self.template_id = os.getenv("MSG91_TEMPLATE_ID", "").strip()
        self._client = client

    def configured(self) -> bool:
        return bool(self.auth_key and self.template_id)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str],
    ) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=20.0)
        try:
            try:
                response = await client.request(
                    method,
                    f"https://control.msg91.com/api/v5/otp{path}",
                    params=params,
                    headers={"authkey": self.auth_key, "Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise PhoneVerificationTransportError(
                    f"MSG91 transport failed: {type(exc).__name__}"
                ) from exc
            try:
                parsed = response.json()
                payload = parsed if isinstance(parsed, dict) else {}
            except ValueError:
                payload = {}
            if response.is_error or str(payload.get("type") or "").lower() == "error":
                message = str(
                    payload.get("message")
                    or payload.get("error")
                    or f"HTTP {response.status_code}"
                )
                if 400 <= response.status_code < 500 or response.status_code == 200:
                    raise PhoneVerificationRejected(
                        f"MSG91 rejected request: {message[:300]}"
                    )
                raise PhoneVerificationTransportError(
                    f"MSG91 failed with HTTP {response.status_code}"
                )
            return payload
        finally:
            if owns_client:
                await client.aclose()

    async def start(self, phone_e164: str, *, channel: str = "sms") -> VerificationStart:
        if channel != "sms":
            raise ValueError("MSG91 direct Verify currently supports sms in Internet Hands")
        if not self.configured():
            raise PhoneVerificationError("MSG91 credentials are not configured")
        params = {
            "template_id": self.template_id,
            "mobile": phone_e164.lstrip("+"),
            "otp_length": os.getenv("MSG91_OTP_LENGTH", "6").strip() or "6",
            "otp_expiry": os.getenv("MSG91_OTP_EXPIRY_MINUTES", "10").strip() or "10",
        }
        payload = await self._request("POST", "", params=params)
        request_id = str(
            payload.get("request_id")
            or payload.get("reqId")
            or f"msg91_{secrets.token_urlsafe(12)}"
        )
        return VerificationStart(
            provider=self.name,
            request_id=request_id,
            channel=channel,
            status="pending",
            metadata={"provider_message": payload.get("message")},
        )

    async def check(
        self, phone_e164: str, request_id: str, code: str
    ) -> VerificationCheck:
        del request_id
        payload = await self._request(
            "GET",
            "/verify",
            params={"otp": code, "mobile": phone_e164.lstrip("+")},
        )
        message = str(payload.get("message") or "").strip().lower()
        approved = (
            str(payload.get("type") or "").lower() == "success"
            or message in {"otp verified success", "number_verified_successfully"}
            or "verified success" in message
        )
        return VerificationCheck(
            provider=self.name,
            request_id="",
            approved=approved,
            status="approved" if approved else "pending",
            metadata={"provider_message": payload.get("message")},
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
        request_body: dict[str, Any] = {
            "brand": self.brand,
            "code_length": 6,
            "workflow": workflow,
        }
        if os.getenv("VONAGE_VERIFY_FRAUD_CHECK", "0") == "1":
            request_body["fraud_check"] = True
        payload = await self._request(
            "POST",
            "/",
            json=request_body,
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
        "msg91": Msg91VerifyProvider(),
        "smsgate": SmsGateVerifyProvider(),
    }
    preferred = [
        item.strip().lower()
        for item in os.getenv("PHONE_VERIFY_PROVIDERS", "twilio,vonage,msg91,smsgate").split(",")
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
        "no phone verification provider is configured; configure Twilio Verify, Vonage Verify, MSG91, or a self-hosted SMS gateway"
    )


def _local_phone_intelligence(phone_e164: str) -> dict[str, Any]:
    normalized = normalize_phone(phone_e164)
    parsed = phonenumbers.parse(normalized.e164, None)
    region = normalized.region_code
    original_carrier = carrier.name_for_number(parsed, "en") or None
    location = geocoder.description_for_number(parsed, "en") or None
    timezones = list(timezone.time_zones_for_number(parsed))
    sms_capable = normalized.number_type in {"mobile", "fixed_line_or_mobile"}
    flags: list[str] = []
    if normalized.number_type == "voip":
        flags.append("voip")
    if normalized.number_type == "premium_rate":
        flags.append("premium_rate")
    if normalized.number_type == "personal_number":
        flags.append("personal_number")
    if normalized.number_type == "unknown":
        flags.append("unknown_type")
    if not sms_capable:
        flags.append("sms_capability_not_guaranteed")

    return {
        "source": "libphonenumber",
        "provider": "libphonenumber",
        "providers_used": ["libphonenumber"],
        "phone": normalized.to_dict(),
        "valid_for_region": bool(
            region and phonenumbers.is_valid_number_for_region(parsed, region)
        ),
        "line_type": normalized.number_type,
        "carrier": original_carrier,
        "original_carrier": original_carrier,
        "carrier_source": "libphonenumber_original_range" if original_carrier else None,
        "location_description": location,
        "timezones": timezones,
        "formats": {
            "e164": phonenumbers.format_number(parsed, PhoneNumberFormat.E164),
            "international": phonenumbers.format_number(
                parsed, PhoneNumberFormat.INTERNATIONAL
            ),
            "national": phonenumbers.format_number(parsed, PhoneNumberFormat.NATIONAL),
            "rfc3966": phonenumbers.format_number(parsed, PhoneNumberFormat.RFC3966),
        },
        "sms_capable_heuristic": sms_capable,
        "delivery_flags": flags,
        "sim_swap": None,
        "external": {},
        "provider_errors": [],
    }


def _merge_external(
    result: dict[str, Any],
    provider: str,
    data: dict[str, Any],
) -> None:
    result.setdefault("external", {})[provider] = data
    result.setdefault("providers_used", []).append(provider)
    if data.get("carrier"):
        result["carrier"] = data["carrier"]
        result["carrier_source"] = provider
    if data.get("line_type"):
        result["line_type"] = data["line_type"]
    if data.get("location") and not result.get("location_description"):
        result["location_description"] = data["location"]
    if data.get("sim_swap") is not None:
        result["sim_swap"] = data["sim_swap"]
    if data.get("mobile_country_code"):
        result["mobile_country_code"] = data["mobile_country_code"]
    if data.get("mobile_network_code"):
        result["mobile_network_code"] = data["mobile_network_code"]
    result["provider"] = provider


async def _lookup_veriphone(
    client: httpx.AsyncClient, phone_e164: str, api_key: str
) -> dict[str, Any]:
    response = await client.get(
        "https://api.veriphone.io/v3/verify",
        params={
            "phone": phone_e164,
            "mode": os.getenv("VERIPHONE_MODE", "static").strip() or "static",
            "record": "false",
        },
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if response.is_error:
        raise PhoneVerificationError(f"Veriphone HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise PhoneVerificationError("Veriphone returned an invalid response")
    return {
        "valid": payload.get("phone_valid", payload.get("valid")),
        "carrier": payload.get("carrier"),
        "line_type": payload.get("phone_type") or payload.get("line_type"),
        "location": payload.get("phone_region") or payload.get("location"),
        "country_code": payload.get("country_code"),
        "e164": payload.get("e164") or payload.get("international_number"),
        "mode": payload.get("mode") or os.getenv("VERIPHONE_MODE", "static"),
    }


async def _lookup_abstract(
    client: httpx.AsyncClient, phone_e164: str, api_key: str
) -> dict[str, Any]:
    response = await client.get(
        "https://phonevalidation.abstractapi.com/v1/",
        params={"api_key": api_key, "phone": phone_e164},
        headers={"Accept": "application/json"},
    )
    if response.is_error:
        raise PhoneVerificationError(f"Abstract Phone Validation HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise PhoneVerificationError("Abstract Phone Validation returned an invalid response")
    return {
        "valid": payload.get("valid"),
        "carrier": payload.get("carrier"),
        "line_type": payload.get("line_type"),
        "location": payload.get("registered_location"),
        "country_code": payload.get("country_code"),
        "e164": payload.get("international_format"),
        "risk_score": payload.get("risk_score"),
    }


async def _lookup_numverify(
    client: httpx.AsyncClient, phone_e164: str, api_key: str
) -> dict[str, Any]:
    response = await client.get(
        "https://api.apilayer.com/number_verification/validate",
        params={"number": phone_e164},
        headers={"apikey": api_key, "Accept": "application/json"},
    )
    if response.is_error:
        raise PhoneVerificationError(f"Numverify HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise PhoneVerificationError("Numverify returned an invalid response")
    return {
        "valid": payload.get("valid"),
        "carrier": payload.get("carrier"),
        "line_type": payload.get("line_type"),
        "location": payload.get("location"),
        "country_code": payload.get("country_code"),
        "e164": payload.get("international_format"),
        "quota": {
            "monthly_limit": response.headers.get("x-ratelimit-limit-month"),
            "monthly_remaining": response.headers.get("x-ratelimit-remaining-month"),
            "daily_limit": response.headers.get("x-ratelimit-limit-day"),
            "daily_remaining": response.headers.get("x-ratelimit-remaining-day"),
        },
    }


async def _lookup_twilio(
    client: httpx.AsyncClient, phone_e164: str
) -> dict[str, Any] | None:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    api_key = os.getenv("TWILIO_API_KEY", "").strip()
    api_secret = os.getenv("TWILIO_API_SECRET", "").strip()
    if not ((account_sid and auth_token) or (api_key and api_secret)):
        return None

    fields = ["line_type_intelligence"]
    if os.getenv("TWILIO_LOOKUP_SIM_SWAP", "0") == "1":
        fields.append("sim_swap")
    auth = (api_key, api_secret) if api_key and api_secret else (account_sid, auth_token)
    response = await client.get(
        f"https://lookups.twilio.com/v2/PhoneNumbers/{phone_e164}",
        params={"Fields": ",".join(fields)},
        auth=auth,
        headers={"Accept": "application/json"},
    )
    if response.is_error:
        raise PhoneVerificationError(f"Twilio Lookup HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise PhoneVerificationError("Twilio Lookup returned an invalid response")

    data: dict[str, Any] = {}
    line = payload.get("line_type_intelligence")
    if isinstance(line, dict):
        data.update(
            {
                "line_type": line.get("type"),
                "carrier": line.get("carrier_name"),
                "mobile_country_code": line.get("mobile_country_code"),
                "mobile_network_code": line.get("mobile_network_code"),
            }
        )
    sim_swap = payload.get("sim_swap")
    if isinstance(sim_swap, dict):
        last_swap = sim_swap.get("last_sim_swap")
        data["sim_swap"] = {
            "last_sim_swap": last_swap if isinstance(last_swap, dict) else None,
            "carrier_name": sim_swap.get("carrier_name"),
            "mobile_country_code": sim_swap.get("mobile_country_code"),
            "mobile_network_code": sim_swap.get("mobile_network_code"),
            "error_code": sim_swap.get("error_code"),
        }
    return data


async def lookup_phone_intelligence(phone_e164: str) -> dict[str, Any]:
    """Return telecom metadata for the signed-in account owner's verified number."""
    result = _local_phone_intelligence(phone_e164)
    configured = [
        item.strip().lower()
        for item in os.getenv(
            "PHONE_INTEL_PROVIDERS",
            "local,veriphone,abstract,numverify,twilio",
        ).split(",")
        if item.strip()
    ]

    async with httpx.AsyncClient(timeout=20.0) as client:
        for provider in configured:
            if provider == "local":
                continue
            try:
                data: dict[str, Any] | None = None
                if provider == "veriphone":
                    key = os.getenv("VERIPHONE_API_KEY", "").strip()
                    if key:
                        data = await _lookup_veriphone(client, phone_e164, key)
                elif provider == "abstract":
                    key = os.getenv("ABSTRACT_PHONE_API_KEY", "").strip()
                    if key:
                        data = await _lookup_abstract(client, phone_e164, key)
                elif provider == "numverify":
                    key = (
                        os.getenv("NUMVERIFY_API_KEY", "").strip()
                        or os.getenv("APILAYER_API_KEY", "").strip()
                    )
                    if key:
                        data = await _lookup_numverify(client, phone_e164, key)
                elif provider == "twilio":
                    data = await _lookup_twilio(client, phone_e164)

                if data:
                    _merge_external(result, provider, data)
            except (httpx.HTTPError, ValueError, PhoneVerificationError) as exc:
                result.setdefault("provider_errors", []).append(
                    {"provider": provider, "error": str(exc)[:300]}
                )

    return result
