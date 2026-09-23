from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

import httpx
import phonenumbers
from phonenumbers import PhoneNumberFormat, PhoneNumberType, carrier, geocoder, timezone

from .execution_meter import record_provider_call
from .tool_mesh import ToolDescriptor


class PhoneIntelligenceError(RuntimeError):
    pass


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


def local_phone_intelligence(
    value: str,
    *,
    default_region: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_phone(value, default_region=default_region)
    parsed = phonenumbers.parse(normalized.e164, None)
    region = normalized.region_code
    original_carrier = carrier.name_for_number(parsed, "en") or None
    location = geocoder.description_for_number(parsed, "en") or None
    timezones = list(timezone.time_zones_for_number(parsed))
    sms_capable = normalized.number_type in {"mobile", "fixed_line_or_mobile"}

    flags: list[str] = []
    if not normalized.possible:
        flags.append("not_possible")
    if not normalized.valid:
        flags.append("not_valid")
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
        "number": normalized.to_dict(),
        "valid_for_region": bool(
            region and phonenumbers.is_valid_number_for_region(parsed, region)
        ),
        "line_type": normalized.number_type,
        "carrier": original_carrier,
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
        "flags": flags,
        "source": "libphonenumber",
    }


def _safe_external_record(provider: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only non-identifying telecom fields from third-party responses."""
    allowed = {
        "valid",
        "carrier",
        "line_type",
        "location",
        "country_code",
        "country_name",
        "e164",
        "risk_score",
        "mobile_country_code",
        "mobile_network_code",
        "sim_swap",
        "quota",
        "mode",
    }
    return {
        "provider": provider,
        **{key: value for key, value in payload.items() if key in allowed},
    }


async def _lookup_veriphone(
    client: httpx.AsyncClient, phone_e164: str, api_key: str
) -> dict[str, Any]:
    record_provider_call("veriphone")
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
        raise PhoneIntelligenceError(f"Veriphone HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise PhoneIntelligenceError("Veriphone returned an invalid response")
    return _safe_external_record(
        "veriphone",
        {
            "valid": payload.get("phone_valid", payload.get("valid")),
            "carrier": payload.get("carrier"),
            "line_type": payload.get("phone_type") or payload.get("line_type"),
            "location": payload.get("phone_region") or payload.get("location"),
            "country_code": payload.get("country_code"),
            "country_name": payload.get("country"),
            "e164": payload.get("e164") or payload.get("international_number"),
            "mode": payload.get("mode") or os.getenv("VERIPHONE_MODE", "static"),
        },
    )


async def _lookup_abstract(
    client: httpx.AsyncClient, phone_e164: str, api_key: str
) -> dict[str, Any]:
    record_provider_call("abstract")
    response = await client.get(
        "https://phonevalidation.abstractapi.com/v1/",
        params={"api_key": api_key, "phone": phone_e164},
        headers={"Accept": "application/json"},
    )
    if response.is_error:
        raise PhoneIntelligenceError(
            f"Abstract Phone Validation HTTP {response.status_code}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise PhoneIntelligenceError("Abstract Phone Validation returned an invalid response")
    return _safe_external_record(
        "abstract",
        {
            "valid": payload.get("valid"),
            "carrier": payload.get("carrier"),
            "line_type": payload.get("line_type"),
            "location": payload.get("registered_location"),
            "country_code": payload.get("country_code"),
            "country_name": payload.get("country_name"),
            "e164": payload.get("international_format"),
            "risk_score": payload.get("risk_score"),
        },
    )


async def _lookup_numverify(
    client: httpx.AsyncClient, phone_e164: str, api_key: str
) -> dict[str, Any]:
    record_provider_call("numverify")
    response = await client.get(
        "https://api.apilayer.com/number_verification/validate",
        params={"number": phone_e164},
        headers={"apikey": api_key, "Accept": "application/json"},
    )
    if response.is_error:
        raise PhoneIntelligenceError(f"Numverify HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise PhoneIntelligenceError("Numverify returned an invalid response")
    return _safe_external_record(
        "numverify",
        {
            "valid": payload.get("valid"),
            "carrier": payload.get("carrier"),
            "line_type": payload.get("line_type"),
            "location": payload.get("location"),
            "country_code": payload.get("country_code"),
            "country_name": payload.get("country_name"),
            "e164": payload.get("international_format"),
            "quota": {
                "monthly_limit": response.headers.get("x-ratelimit-limit-month"),
                "monthly_remaining": response.headers.get("x-ratelimit-remaining-month"),
                "daily_limit": response.headers.get("x-ratelimit-limit-day"),
                "daily_remaining": response.headers.get("x-ratelimit-remaining-day"),
            },
        },
    )


async def _lookup_twilio(
    client: httpx.AsyncClient,
    phone_e164: str,
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

    record_provider_call("twilio")
    response = await client.get(
        f"https://lookups.twilio.com/v2/PhoneNumbers/{phone_e164}",
        params={"Fields": ",".join(fields)},
        auth=auth,
        headers={"Accept": "application/json"},
    )
    if response.is_error:
        raise PhoneIntelligenceError(f"Twilio Lookup HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise PhoneIntelligenceError("Twilio Lookup returned an invalid response")

    record: dict[str, Any] = {}
    line = payload.get("line_type_intelligence")
    if isinstance(line, dict):
        record.update(
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
        record["sim_swap"] = {
            "last_sim_swap": last_swap if isinstance(last_swap, dict) else None,
            "carrier_name": sim_swap.get("carrier_name"),
            "mobile_country_code": sim_swap.get("mobile_country_code"),
            "mobile_network_code": sim_swap.get("mobile_network_code"),
            "error_code": sim_swap.get("error_code"),
        }
    return _safe_external_record("twilio", record)


def configured_external_providers() -> dict[str, bool]:
    return {
        "veriphone": bool(os.getenv("VERIPHONE_API_KEY", "").strip()),
        "abstract": bool(os.getenv("ABSTRACT_PHONE_API_KEY", "").strip()),
        "numverify": bool(
            os.getenv("NUMVERIFY_API_KEY", "").strip()
            or os.getenv("APILAYER_API_KEY", "").strip()
        ),
        "twilio": bool(
            (
                os.getenv("TWILIO_ACCOUNT_SID", "").strip()
                and os.getenv("TWILIO_AUTH_TOKEN", "").strip()
            )
            or (
                os.getenv("TWILIO_API_KEY", "").strip()
                and os.getenv("TWILIO_API_SECRET", "").strip()
            )
        ),
    }


async def lookup_phone_intelligence(
    value: str,
    *,
    default_region: str | None = None,
    external: bool = True,
    providers: list[str] | None = None,
) -> dict[str, Any]:
    local = local_phone_intelligence(value, default_region=default_region)
    e164 = str(local["formats"]["e164"])
    result: dict[str, Any] = {
        **local,
        "providers_used": ["libphonenumber"],
        "external": {},
        "provider_errors": [],
        "policy": {
            "subscriber_identity": False,
            "public_business_identity": False,
            "note": (
                "This tool returns telecom metadata and risk signals only. "
                "It does not identify a private subscriber or SIM owner."
            ),
        },
    }

    if not external:
        return result

    configured_order = [
        item.strip().lower()
        for item in os.getenv(
            "PHONE_INTEL_PROVIDERS",
            "veriphone,abstract,numverify,twilio",
        ).split(",")
        if item.strip()
    ]
    selected = [item.lower() for item in providers] if providers else configured_order
    selected = [item for item in selected if item in {"veriphone", "abstract", "numverify", "twilio"}]

    async with httpx.AsyncClient(timeout=20.0) as client:
        for provider in selected:
            try:
                record: dict[str, Any] | None = None
                if provider == "veriphone":
                    key = os.getenv("VERIPHONE_API_KEY", "").strip()
                    if key:
                        record = await _lookup_veriphone(client, e164, key)
                elif provider == "abstract":
                    key = os.getenv("ABSTRACT_PHONE_API_KEY", "").strip()
                    if key:
                        record = await _lookup_abstract(client, e164, key)
                elif provider == "numverify":
                    key = (
                        os.getenv("NUMVERIFY_API_KEY", "").strip()
                        or os.getenv("APILAYER_API_KEY", "").strip()
                    )
                    if key:
                        record = await _lookup_numverify(client, e164, key)
                elif provider == "twilio":
                    record = await _lookup_twilio(client, e164)

                if not record:
                    continue
                result["external"][provider] = record
                result["providers_used"].append(provider)
                if record.get("carrier"):
                    result["carrier"] = record["carrier"]
                    result["carrier_source"] = provider
                if record.get("line_type"):
                    result["line_type"] = record["line_type"]
                if record.get("location") and not result.get("location_description"):
                    result["location_description"] = record["location"]
                if record.get("mobile_country_code"):
                    result["mobile_country_code"] = record["mobile_country_code"]
                if record.get("mobile_network_code"):
                    result["mobile_network_code"] = record["mobile_network_code"]
                if record.get("sim_swap") is not None:
                    result["sim_swap"] = record["sim_swap"]
                if record.get("risk_score") is not None:
                    result["risk_score"] = record["risk_score"]
            except (httpx.HTTPError, ValueError, PhoneIntelligenceError) as exc:
                result["provider_errors"].append(
                    {"provider": provider, "error": str(exc)[:300]}
                )

    return result


class PhoneIntelligenceProvider:
    """Tool Mesh provider for non-identifying phone-number intelligence."""

    name = "phoneintel"

    async def status(self) -> dict[str, Any]:
        configured = configured_external_providers()
        return {
            "configured": True,
            "searchable": True,
            "executable": True,
            "kind": "phone-intelligence",
            "tool_count": 1,
            "local_provider": "libphonenumber",
            "external_providers": configured,
        }

    async def search(self, query: str, *, limit: int = 10) -> list[ToolDescriptor]:
        descriptor = await self.describe("lookup")
        words = [word for word in query.casefold().split() if word]
        haystack = " ".join(
            [descriptor.tool_id, descriptor.name, descriptor.description, *descriptor.tags]
        ).casefold()
        if words and not any(word in haystack for word in words):
            return []
        return [descriptor][: max(1, min(limit, 10))]

    async def describe(self, tool_id: str) -> ToolDescriptor:
        if tool_id != "lookup":
            raise ValueError(f"unknown phoneintel tool: {tool_id}")
        return ToolDescriptor(
            ref="phoneintel:lookup",
            provider=self.name,
            tool_id="lookup",
            name="Phone number intelligence",
            description=(
                "Inspect a phone number for validity, country/region, carrier, line type, "
                "formatting, time zones, MCC/MNC and configured telecom risk signals. "
                "Does not return private subscriber/SIM-owner identity."
            ),
            input_schema={
                "type": "object",
                "required": ["number"],
                "properties": {
                    "number": {"type": "string", "minLength": 3, "maxLength": 64},
                    "region": {"type": "string", "minLength": 2, "maxLength": 2},
                    "external": {"type": "boolean"},
                    "providers": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["veriphone", "abstract", "numverify", "twilio"],
                        },
                        "maxItems": 4,
                    },
                },
                "additionalProperties": False,
            },
            output_schema={},
            tags=[
                "phone",
                "telecom",
                "carrier",
                "line-type",
                "sim-swap",
                "mcc",
                "mnc",
                "lookup",
            ],
            requires_auth=False,
            side_effecting=False,
            metadata={
                "configured": True,
                "local_free": True,
                "subscriber_identity": False,
            },
        )

    async def execute(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        account: str | None = None,
        wait_seconds: int = 30,
        timeout_seconds: int = 60,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del account, wait_seconds, timeout_seconds, options
        await self.describe(tool_id)
        number = str(arguments.get("number") or "").strip()
        if not number:
            raise ValueError("number is required")
        region = str(arguments.get("region") or "").strip() or None
        providers_raw = arguments.get("providers")
        providers = (
            [str(item) for item in providers_raw]
            if isinstance(providers_raw, list)
            else None
        )
        data = await lookup_phone_intelligence(
            number,
            default_region=region,
            external=bool(arguments.get("external", False)),
            providers=providers,
        )
        return {
            "status": "completed",
            "data": data,
            "metadata": {
                "provider": "phoneintel",
                "subscriber_identity": False,
            },
        }

    async def job_status(self, job_id: str, *, wait_seconds: int = 0) -> dict[str, Any]:
        del job_id, wait_seconds
        raise ValueError("phone intelligence lookups complete synchronously")

    async def result_page(
        self, result_id: str, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        del result_id, offset, limit
        raise ValueError("phone intelligence returns bounded inline results")
