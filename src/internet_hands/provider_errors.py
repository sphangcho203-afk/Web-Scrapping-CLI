from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    category: str
    retryable: bool
    status_code: int | None = None
    retry_after_seconds: float | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_retry_budget() -> int:
    return _env_int(
        "OPENCRAWL_PROVIDER_READ_RETRIES",
        1,
        minimum=0,
        maximum=3,
    )


def retry_base_ms() -> int:
    return _env_int(
        "OPENCRAWL_PROVIDER_RETRY_BASE_MS",
        200,
        minimum=50,
        maximum=5000,
    )


def retry_max_wait_ms() -> int:
    return _env_int(
        "OPENCRAWL_PROVIDER_RETRY_MAX_WAIT_MS",
        2000,
        minimum=100,
        maximum=10000,
    )


def _status_code(exc: BaseException | None) -> int | None:
    if exc is None:
        return None
    direct = getattr(exc, "status_code", None)
    if isinstance(direct, int):
        return direct
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _retry_after(exc: BaseException | None) -> float | None:
    if exc is None:
        return None
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        raw = headers.get("retry-after")
    except Exception:  # noqa: BLE001 - third-party header mapping boundary
        return None
    if raw is None:
        return None
    text = str(raw).strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(text)
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        return max(0.0, (target - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def classify_provider_failure(
    *,
    exc: BaseException | None = None,
    status: str | None = None,
    error: str | None = None,
) -> ProviderFailure:
    code = _status_code(exc)
    retry_after = _retry_after(exc)
    detail = str(error if error is not None else exc or "").strip()[:500] or None
    normalized = (detail or "").casefold()
    status_name = str(status or "").strip().casefold()

    if status_name in {"blocked"} or any(
        marker in normalized
        for marker in (
            "captcha",
            "verify you are human",
            "checking your browser",
            "challenge-platform",
            "cf-chl-",
            "access denied",
        )
    ):
        return ProviderFailure("blocked", False, code, retry_after, detail)

    if code in {401, 403} or any(
        marker in normalized
        for marker in (
            "unauthorized",
            "forbidden",
            "invalid api key",
            "invalid token",
            "authentication failed",
        )
    ):
        return ProviderFailure("auth", False, code, retry_after, detail)

    if code == 404 or "not found" in normalized:
        return ProviderFailure("not_found", False, code, retry_after, detail)

    if code == 429 or any(
        marker in normalized
        for marker in (
            "rate limit",
            "rate-limit",
            "too many requests",
            "quota exceeded",
        )
    ):
        return ProviderFailure("rate_limited", True, code, retry_after, detail)

    class_name = type(exc).__name__.casefold() if exc is not None else ""
    if code == 408 or "timeout" in class_name or any(
        marker in normalized for marker in ("timed out", "timeout", "deadline exceeded")
    ):
        return ProviderFailure("timeout", True, code, retry_after, detail)

    if code in {425, 500, 502, 503, 504} or any(
        marker in normalized
        for marker in (
            "connection reset",
            "connection refused",
            "connecterror",
            "connectionerror",
            "temporarily unavailable",
            "service unavailable",
            "bad gateway",
            "gateway timeout",
            "econnreset",
            "econnrefused",
        )
    ):
        return ProviderFailure("upstream_unavailable", True, code, retry_after, detail)

    if code in {400, 405, 409, 410, 415, 422} or any(
        marker in normalized
        for marker in (
            "invalid request",
            "validation error",
            "schema",
            "missing required",
            "bad request",
        )
    ):
        return ProviderFailure("invalid_request", False, code, retry_after, detail)

    if status_name in {"failed", "error"}:
        return ProviderFailure("unknown", False, code, retry_after, detail)

    return ProviderFailure("unknown", False, code, retry_after, detail)


def retry_delay_seconds(failure: ProviderFailure, *, attempt: int) -> float | None:
    if not failure.retryable:
        return None
    max_wait = retry_max_wait_ms() / 1000.0
    if failure.retry_after_seconds is not None:
        if failure.retry_after_seconds > max_wait:
            return None
        return failure.retry_after_seconds
    base = retry_base_ms() / 1000.0
    delay = base * (2 ** max(0, int(attempt) - 1))
    return min(max_wait, delay)
