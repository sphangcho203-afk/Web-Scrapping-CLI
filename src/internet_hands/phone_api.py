from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .control_api import _json_error, _require_user, _require_verified, store
from .control_store import ControlError
from .phone_identity import (
    PhoneVerificationError,
    PhoneVerificationRejected,
    PhoneVerificationTransportError,
    lookup_phone_intelligence,
    mask_phone,
    normalize_phone,
    verification_providers,
)
from .phone_store import PhoneIdentityStore

router = APIRouter()
phone_store = PhoneIdentityStore(store)


def _account_user(request: Request) -> dict[str, Any]:
    return _require_verified(_require_user(request))


def _public_status(row: dict[str, Any]) -> dict[str, Any]:
    phone = row.get("phone_e164")
    return {
        "configured": bool(phone),
        "phone": phone,
        "masked_phone": mask_phone(phone) if phone else None,
        "verified": bool(row.get("verified_at")),
        "verified_at": row.get("verified_at"),
        "provider": row.get("verification_provider"),
        "country_code": row.get("country_code"),
        "region_code": row.get("region_code"),
        "number_type": row.get("number_type"),
        "line_type": row.get("line_type"),
        "carrier_name": row.get("carrier_name"),
        "risk": row.get("risk_metadata") or {},
        "updated_at": row.get("updated_at"),
    }


def _provider_for_name(name: str):
    for provider in verification_providers():
        if provider.name == name:
            return provider
    raise PhoneVerificationError(f"phone verification provider is unavailable: {name}")


def _choose_provider(requested: str | None = None):
    requested = str(requested or "").strip().lower()
    providers = verification_providers()
    if requested:
        for provider in providers:
            if provider.name == requested:
                if not provider.configured():
                    raise PhoneVerificationError(
                        f"{requested} phone verification is not configured"
                    )
                return provider
        raise ValueError("unsupported phone verification provider")
    for provider in providers:
        if provider.configured():
            return provider
    raise PhoneVerificationError(
        "no phone verification provider is configured; configure Twilio Verify, Vonage Verify, MSG91, or a self-hosted SMS gateway"
    )


def _provider_channel(provider_name: str, requested: str) -> str:
    channel = requested.strip().lower()
    if channel not in {"sms", "voice", "whatsapp"}:
        raise ValueError("channel must be sms, voice, or whatsapp")
    if provider_name == "twilio":
        return "call" if channel == "voice" else channel
    if provider_name == "vonage":
        if channel == "whatsapp":
            raise ValueError("whatsapp verification requires the Twilio provider")
        return channel
    if provider_name in {"msg91", "smsgate"}:
        if channel != "sms":
            raise ValueError(f"{provider_name} verification currently supports SMS only")
        return channel
    return channel


def _intelligence_metadata(intelligence: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": intelligence.get("source"),
        "provider": intelligence.get("provider"),
        "providers_used": intelligence.get("providers_used") or [],
        "original_carrier": intelligence.get("original_carrier"),
        "carrier_source": intelligence.get("carrier_source"),
        "location_description": intelligence.get("location_description"),
        "timezones": intelligence.get("timezones") or [],
        "formats": intelligence.get("formats") or {},
        "valid_for_region": intelligence.get("valid_for_region"),
        "sms_capable_heuristic": intelligence.get("sms_capable_heuristic"),
        "delivery_flags": intelligence.get("delivery_flags") or [],
        "sim_swap": intelligence.get("sim_swap"),
        "mobile_country_code": intelligence.get("mobile_country_code"),
        "mobile_network_code": intelligence.get("mobile_network_code"),
        "external": intelligence.get("external") or {},
        "provider_errors": intelligence.get("provider_errors") or [],
        "checked_at": datetime.now(UTC).isoformat(),
    }


@router.get("/api/auth/phone/providers")
async def phone_provider_status(request: Request):
    _account_user(request)
    rows: list[dict[str, Any]] = []
    for provider in verification_providers():
        rows.append(
            {
                "provider": provider.name,
                "configured": provider.configured(),
                "channels": (
                    ["sms", "voice", "whatsapp"]
                    if provider.name == "twilio"
                    else ["sms", "voice"]
                    if provider.name == "vonage"
                    else ["sms"]
                ),
            }
        )
    intelligence = [
        {"provider": "libphonenumber", "configured": True, "cost": "free_offline"},
        {
            "provider": "veriphone",
            "configured": bool(os.getenv("VERIPHONE_API_KEY", "").strip()),
            "cost": "free_tier_or_paid",
        },
        {
            "provider": "abstract",
            "configured": bool(os.getenv("ABSTRACT_PHONE_API_KEY", "").strip()),
            "cost": "free_tier_or_paid",
        },
        {
            "provider": "numverify",
            "configured": bool(
                os.getenv("NUMVERIFY_API_KEY", "").strip()
                or os.getenv("APILAYER_API_KEY", "").strip()
            ),
            "cost": "free_tier_or_paid",
        },
        {
            "provider": "twilio_lookup",
            "configured": bool(
                (
                    os.getenv("TWILIO_ACCOUNT_SID", "").strip()
                    and os.getenv("TWILIO_AUTH_TOKEN", "").strip()
                )
                or (
                    os.getenv("TWILIO_API_KEY", "").strip()
                    and os.getenv("TWILIO_API_SECRET", "").strip()
                )
            ),
            "cost": "paid_or_account_entitlement",
        },
    ]
    return {
        "providers": rows,
        "intelligence_providers": intelligence,
        "local_validation": "libphonenumber",
        "subscriber_identity_lookup": False,
        "policy": (
            "Internet Hands verifies possession of a phone number and may collect "
            "non-identifying telecom risk signals. It does not reverse-identify a person "
            "behind a SIM."
        ),
    }


@router.get("/api/auth/phone/status")
async def phone_status(request: Request):
    user = _account_user(request)
    row = phone_store.status(user["id"])
    pending = phone_store.pending(user["id"])
    return {
        **_public_status(row),
        "pending": (
            {
                "masked_phone": mask_phone(str(pending["phone_e164"])),
                "provider": pending["provider"],
                "channel": pending["channel"],
                "expires_at": pending["expires_at"],
                "attempts": int(pending.get("attempts") or 0),
            }
            if pending
            else None
        ),
    }


@router.post("/api/auth/phone/start")
async def phone_start(request: Request):
    user = _account_user(request)
    if not phone_store.send_allowed(user["id"]):
        raise HTTPException(
            status_code=429,
            detail="wait before requesting another phone verification code",
        )

    body = await request.json()
    try:
        normalized = normalize_phone(
            str(body.get("phone") or ""),
            default_region=str(body.get("region") or "").strip() or None,
        )
        requested_channel = str(body.get("channel") or "sms")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    requested_provider = str(body.get("provider") or "").strip().lower()
    providers = verification_providers()
    if requested_provider:
        providers = [provider for provider in providers if provider.name == requested_provider]
        if not providers:
            raise HTTPException(status_code=400, detail="unsupported phone verification provider")

    started = None
    provider = None
    rejections: list[str] = []
    for candidate in providers:
        if not candidate.configured():
            continue
        try:
            provider_channel = _provider_channel(candidate.name, requested_channel)
            started = await candidate.start(normalized.e164, channel=provider_channel)
            provider = candidate
            break
        except PhoneVerificationRejected as exc:
            # Provider explicitly rejected before accepting the verification request.
            # This is the only send failure class where trying another provider is safe.
            rejections.append(f"{candidate.name}: {exc}")
            if requested_provider:
                break
            continue
        except ValueError as exc:
            rejections.append(f"{candidate.name}: {exc}")
            if requested_provider:
                break
            continue
        except PhoneVerificationTransportError as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"{candidate.name} verification transport failed; the send outcome may be "
                    "unknown, so Internet Hands did not retry through another provider"
                ),
            ) from exc
        except PhoneVerificationError as exc:
            rejections.append(f"{candidate.name}: {exc}")
            if requested_provider:
                break
            continue

    if started is None or provider is None:
        detail = "; ".join(rejections[-3:]) or (
            "no phone verification provider is configured; configure Twilio Verify or Vonage Verify"
        )
        raise HTTPException(status_code=503, detail=detail)

    record = phone_store.begin_verification(
        user_id=user["id"],
        phone_e164=normalized.e164,
        country_code=normalized.country_code,
        region_code=normalized.region_code,
        number_type=normalized.number_type,
        provider=started.provider,
        provider_request_id=started.request_id,
        channel=requested_channel,
        metadata={
            "provider_status": started.status,
            "provider_metadata": started.metadata,
            "normalized": normalized.to_dict(),
        },
    )
    return {
        "ok": True,
        "verification_id": record["id"],
        "masked_phone": mask_phone(normalized.e164),
        "provider": started.provider,
        "channel": requested_channel,
        "status": started.status,
        "expires_at": record["expires_at"],
        "message": "Verification code sent. Enter the code to prove control of this number.",
    }


@router.post("/api/auth/phone/confirm")
async def phone_confirm(request: Request):
    user = _account_user(request)
    body = await request.json()
    code = "".join(ch for ch in str(body.get("code") or "") if ch.isdigit())
    if len(code) < 4 or len(code) > 10:
        raise HTTPException(status_code=400, detail="enter the verification code")

    pending = phone_store.pending(user["id"])
    if not pending:
        raise HTTPException(
            status_code=409,
            detail="phone verification is missing or expired; request a new code",
        )
    if int(pending.get("attempts") or 0) >= 5:
        raise HTTPException(
            status_code=429,
            detail="too many verification attempts; request a new code",
        )

    try:
        provider = _provider_for_name(str(pending["provider"]))
        if not provider.configured():
            raise PhoneVerificationError(
                f"{pending['provider']} phone verification is no longer configured"
            )
        result = await provider.check(
            str(pending["phone_e164"]),
            str(pending["provider_request_id"]),
            code,
        )
    except PhoneVerificationRejected as exc:
        attempts = phone_store.record_failed_attempt(
            str(pending["id"]),
            provider_status="rejected",
        )
        raise HTTPException(
            status_code=400,
            detail={
                "message": "verification code is invalid or was rejected",
                "attempts": attempts,
            },
        ) from exc
    except PhoneVerificationTransportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PhoneVerificationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not result.approved:
        attempts = phone_store.record_failed_attempt(
            str(pending["id"]),
            provider_status=result.status,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "message": "verification code is invalid or expired",
                "attempts": attempts,
            },
        )

    try:
        row = phone_store.complete(
            verification_id=str(pending["id"]),
            user_id=user["id"],
            provider=result.provider,
            metadata={
                "provider_status": result.status,
                "provider_metadata": result.metadata,
            },
        )
    except ControlError as exc:
        raise _json_error(exc) from exc

    # Enrichment is deliberately non-blocking for verification. Ownership proof stays
    # valid even if a carrier/risk provider is temporarily unavailable.
    intelligence: dict[str, Any] | None = None
    try:
        intelligence = await lookup_phone_intelligence(str(row["phone_e164"]))
        phone_store.update_intelligence(
            user["id"],
            carrier_name=intelligence.get("carrier"),
            line_type=intelligence.get("line_type"),
            risk_metadata=_intelligence_metadata(intelligence),
        )
    except Exception:  # noqa: BLE001 -- enrichment must never invalidate ownership proof
        intelligence = None

    return {
        "ok": True,
        "verified": True,
        "phone": str(row["phone_e164"]),
        "masked_phone": mask_phone(str(row["phone_e164"])),
        "provider": result.provider,
        "verified_at": row["completed_at"],
        "intelligence": intelligence,
    }


@router.post("/api/auth/phone/intelligence")
async def refresh_phone_intelligence(request: Request):
    user = _account_user(request)
    current = phone_store.status(user["id"])
    if not current.get("verified_at") or not current.get("phone_e164"):
        raise HTTPException(status_code=409, detail="verify a phone number first")

    intelligence = await lookup_phone_intelligence(str(current["phone_e164"]))
    phone_store.update_intelligence(
        user["id"],
        carrier_name=intelligence.get("carrier"),
        line_type=intelligence.get("line_type"),
        risk_metadata={
            "source": intelligence.get("source"),
            "provider": intelligence.get("provider"),
            "sim_swap": intelligence.get("sim_swap"),
            "mobile_country_code": intelligence.get("mobile_country_code"),
            "mobile_network_code": intelligence.get("mobile_network_code"),
            "provider_error": intelligence.get("provider_error"),
            "checked_at": datetime.now(UTC).isoformat(),
        },
    )
    return {
        "ok": True,
        "phone": str(current["phone_e164"]),
        "masked_phone": mask_phone(str(current["phone_e164"])),
        "intelligence": intelligence,
    }


@router.delete("/api/auth/phone")
async def remove_phone_identity(request: Request):
    user = _account_user(request)
    removed = phone_store.remove(user["id"])
    return {"ok": True, "removed": removed}
