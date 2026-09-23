from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256
from fastapi import HTTPException

from internet_hands import monitor_executor


def _segment(value: dict) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_cron_secret_auth_is_optional_legacy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRON_SECRET", raising=False)
    assert monitor_executor._cron_secret_authorized(None) is False
    monkeypatch.setenv("CRON_SECRET", "expected")
    assert monitor_executor._cron_secret_authorized("Bearer wrong") is False
    assert monitor_executor._cron_secret_authorized("Bearer expected") is True


@pytest.mark.asyncio
async def test_github_oidc_scheduler_identity_is_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private_key.public_key().public_numbers()
    now = int(monitor_executor.time.time())
    header = _segment({"alg": "RS256", "kid": "test-key"})
    claims = _segment(
        {
            "iss": monitor_executor.GITHUB_OIDC_ISSUER,
            "aud": monitor_executor.GITHUB_OIDC_AUDIENCE,
            "sub": monitor_executor.GITHUB_SCHEDULER_SUBJECT,
            "nbf": now - 5,
            "exp": now + 60,
        }
    )
    signature = private_key.sign(
        f"{header}.{claims}".encode(), padding.PKCS1v15(), SHA256()
    )
    token = f"{header}.{claims}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"

    def encoded(value: int) -> str:
        size = (value.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(value.to_bytes(size, "big")).decode().rstrip("=")

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"keys": [{"kid": "test-key", "kty": "RSA", "n": encoded(public.n), "e": encoded(public.e)}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url: str):
            return Response()

    monkeypatch.setattr(monitor_executor.httpx, "AsyncClient", lambda **_kwargs: Client())
    await monitor_executor._github_oidc_authorized(token)


@pytest.mark.asyncio
async def test_github_oidc_rejects_wrong_subject() -> None:
    now = int(monitor_executor.time.time())
    token = ".".join(
        [
            _segment({"alg": "RS256", "kid": "x"}),
            _segment(
                {
                    "iss": monitor_executor.GITHUB_OIDC_ISSUER,
                    "aud": monitor_executor.GITHUB_OIDC_AUDIENCE,
                    "sub": "repo:someone/else:ref:refs/heads/main",
                    "nbf": now - 5,
                    "exp": now + 60,
                }
            ),
            "signature",
        ]
    )
    with pytest.raises(HTTPException) as exc:
        await monitor_executor._github_oidc_authorized(token)
    assert exc.value.status_code == 401


def test_monitor_timeout_is_bounded() -> None:
    assert monitor_executor._timeout_for({"config": {"timeout_seconds": 0}}) == 1.0
    assert monitor_executor._timeout_for({"config": {"timeout_seconds": 999}}) == 20.0
    assert monitor_executor._timeout_for({"config": {"timeout_seconds": "bad"}}) == 10.0


def test_execution_plane_uses_skip_locked_and_public_fetcher() -> None:
    source = Path("src/internet_hands/monitor_executor.py").read_text(encoding="utf-8")
    assert "FOR UPDATE SKIP LOCKED" in source
    assert "health_check(target" in source
    assert "next_check_at = now()" in source
    assert "ih_monitor_runs" in source
    assert "last_checked_at" in source


def test_scheduler_route_and_oidc_workflow_contract() -> None:
    source = Path("src/internet_hands/saas_app.py").read_text(encoding="utf-8")
    executor = Path("src/internet_hands/monitor_executor.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/monitor-scheduler.yml").read_text(encoding="utf-8")
    assert "monitor_executor_router" in source
    assert 'router.get("/api/internal/monitors/tick")' in executor
    assert "GITHUB_OIDC_AUDIENCE" in executor
    assert "id-token: write" in workflow
    assert "*/5 * * * *" in workflow
    assert "ACTIONS_ID_TOKEN_REQUEST_URL" in workflow
    assert "refs/heads/main" in executor
    assert "https://web-scrapping-cli.vercel.app/api/internal/monitors/tick" in workflow
    assert "https://web-scrapping-cli.vercel.app/api/internal/system/health" in workflow
