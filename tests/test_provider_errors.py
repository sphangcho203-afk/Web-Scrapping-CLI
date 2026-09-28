from __future__ import annotations

import httpx
import pytest

from internet_hands.provider_errors import (
    classify_provider_failure,
    read_retry_budget,
    retry_delay_seconds,
    safe_provider_error,
)


def _http_error(status: int, *, retry_after: str | None = None) -> httpx.HTTPStatusError:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    request = httpx.Request("GET", "https://provider.example/test")
    response = httpx.Response(status, request=request, headers=headers)
    return httpx.HTTPStatusError(
        f"provider returned {status}",
        request=request,
        response=response,
    )


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_upstream_5xx_is_retryable(status: int) -> None:
    failure = classify_provider_failure(exc=_http_error(status))
    assert failure.category == "upstream_unavailable"
    assert failure.retryable is True
    assert failure.status_code == status


def test_rate_limit_honors_short_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_RETRY_MAX_WAIT_MS", "2000")
    failure = classify_provider_failure(exc=_http_error(429, retry_after="1.5"))
    assert failure.category == "rate_limited"
    assert failure.retryable is True
    assert retry_delay_seconds(failure, attempt=1) == pytest.approx(1.5)


def test_rate_limit_refuses_long_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_RETRY_MAX_WAIT_MS", "1000")
    failure = classify_provider_failure(exc=_http_error(429, retry_after="60"))
    assert failure.retryable is True
    assert retry_delay_seconds(failure, attempt=1) is None


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_are_not_retried(status: int) -> None:
    failure = classify_provider_failure(exc=_http_error(status))
    assert failure.category == "auth"
    assert failure.retryable is False
    assert retry_delay_seconds(failure, attempt=1) is None


def test_not_found_is_not_retried() -> None:
    failure = classify_provider_failure(exc=_http_error(404))
    assert failure.category == "not_found"
    assert failure.retryable is False


def test_captcha_or_access_denied_is_blocked_not_retryable() -> None:
    captcha = classify_provider_failure(
        status="blocked",
        error="CAPTCHA verify you are human",
    )
    denied = classify_provider_failure(error="Access Denied by upstream challenge")
    assert captcha.category == "blocked" and captcha.retryable is False
    assert denied.category == "blocked" and denied.retryable is False


def test_validation_error_is_not_retried() -> None:
    failure = classify_provider_failure(
        status="failed",
        error="validation error: missing required field",
    )
    assert failure.category == "invalid_request"
    assert failure.retryable is False


def test_timeout_is_retryable() -> None:
    failure = classify_provider_failure(exc=TimeoutError("provider timed out"))
    assert failure.category == "timeout"
    assert failure.retryable is True


def test_unknown_failure_defaults_to_no_retry() -> None:
    failure = classify_provider_failure(
        status="failed",
        error="some provider-specific opaque failure",
    )
    assert failure.category == "unknown"
    assert failure.retryable is False


def test_retry_budget_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAWL_PROVIDER_READ_RETRIES", "999")
    assert read_retry_budget() == 3
    monkeypatch.setenv("OPENCRAWL_PROVIDER_READ_RETRIES", "-99")
    assert read_retry_budget() == 0



def test_provider_error_redacts_query_credentials_and_bearer_tokens() -> None:
    message = (
        "Client error for url "
        "'https://api.example.test/v1?q=x&key=rawg-secret&access_token=token-secret' "
        "Authorization: Bearer eyJ.secret.value client_secret=very-secret"
    )

    safe = safe_provider_error(message)

    assert safe is not None
    assert "rawg-secret" not in safe
    assert "token-secret" not in safe
    assert "eyJ.secret.value" not in safe
    assert "very-secret" not in safe
    assert "key=[REDACTED]" in safe
    assert "access_token=[REDACTED]" in safe
    assert "Authorization=[REDACTED]" in safe
    assert "client_secret=[REDACTED]" in safe


def test_classified_http_error_never_exposes_secret_url_parameters() -> None:
    request = httpx.Request(
        "GET",
        "https://api.rawg.io/api/games?key=operator-secret&search=halo",
    )
    response = httpx.Response(503, request=request)
    exc = httpx.HTTPStatusError(
        "provider failed",
        request=request,
        response=response,
    )

    failure = classify_provider_failure(
        exc=exc,
        error=f"{exc} url={request.url}",
    )

    assert failure.category == "upstream_unavailable"
    assert failure.detail is not None
    assert "operator-secret" not in failure.detail
    assert "key=[REDACTED]" in failure.detail
