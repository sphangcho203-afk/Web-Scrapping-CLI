from __future__ import annotations

import base64
import json
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256
from fastapi import APIRouter, Header, HTTPException

from .control_store import ControlStore
from .fetcher import health_check

router = APIRouter()
store = ControlStore()

MAX_BATCH = 10
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_TIMEOUT_SECONDS = 20.0
GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
GITHUB_OIDC_AUDIENCE = "internet-hands-monitor-scheduler"
GITHUB_SCHEDULER_SUBJECT = (
    "repo:sphangcho203-afk/Web-Scrapping-CLI:ref:refs/heads/rebuild/cognitive-ui-v1"
)
GITHUB_JWKS_URL = f"{GITHUB_OIDC_ISSUER}/.well-known/jwks"


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _decode_json_segment(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(_b64url_decode(value))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="invalid scheduler token") from exc
    if not isinstance(decoded, dict):
        raise HTTPException(status_code=401, detail="invalid scheduler token")
    return decoded


async def _github_oidc_authorized(token: str) -> None:
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="invalid scheduler token")
    header, claims = _decode_json_segment(parts[0]), _decode_json_segment(parts[1])
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise HTTPException(status_code=401, detail="invalid scheduler token")

    now = int(time.time())
    if (
        claims.get("iss") != GITHUB_OIDC_ISSUER
        or claims.get("aud") != GITHUB_OIDC_AUDIENCE
        or claims.get("sub") != GITHUB_SCHEDULER_SUBJECT
        or int(claims.get("exp", 0)) < now
        or int(claims.get("nbf", 0)) > now + 30
    ):
        raise HTTPException(status_code=401, detail="unauthorized scheduler identity")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(GITHUB_JWKS_URL)
            response.raise_for_status()
            keys = response.json().get("keys", [])
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="scheduler identity verification unavailable") from exc

    key = next((item for item in keys if item.get("kid") == header["kid"]), None)
    if not key or key.get("kty") != "RSA":
        raise HTTPException(status_code=401, detail="unknown scheduler signing key")
    try:
        public_key = rsa.RSAPublicNumbers(
            int.from_bytes(_b64url_decode(key["e"]), "big"),
            int.from_bytes(_b64url_decode(key["n"]), "big"),
        ).public_key()
        public_key.verify(
            _b64url_decode(parts[2]),
            f"{parts[0]}.{parts[1]}".encode(),
            padding.PKCS1v15(),
            SHA256(),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="invalid scheduler signature") from exc
    except Exception as exc:  # cryptography exposes backend-specific verification errors
        raise HTTPException(status_code=401, detail="invalid scheduler signature") from exc


def _cron_secret_authorized(authorization: str | None) -> bool:
    secret = os.getenv("CRON_SECRET")
    return bool(secret and authorization == f"Bearer {secret}")


async def _scheduler_authorized(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthorized")
    if _cron_secret_authorized(authorization):
        return
    await _github_oidc_authorized(authorization.removeprefix("Bearer "))


def _claim_due_monitors(limit: int = MAX_BATCH) -> list[dict[str, Any]]:
    """Atomically lease due work by advancing next_check_at before network I/O."""
    bounded = max(1, min(int(limit), MAX_BATCH))
    with store._connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH due AS (
                SELECT id
                FROM ih_monitors
                WHERE enabled = true
                  AND (next_check_at IS NULL OR next_check_at <= now())
                ORDER BY next_check_at NULLS FIRST, created_at
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            UPDATE ih_monitors AS monitor
            SET next_check_at = now() + (monitor.interval_minutes || ' minutes')::interval,
                updated_at = now()
            FROM due
            WHERE monitor.id = due.id
            RETURNING monitor.*
            """,
            (bounded,),
        )
        rows = [dict(row) for row in cur.fetchall()]
        conn.commit()
    return rows


def _timeout_for(monitor: dict[str, Any]) -> float:
    config = monitor.get("config") or {}
    try:
        requested = float(config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        requested = DEFAULT_TIMEOUT_SECONDS
    return max(1.0, min(requested, MAX_TIMEOUT_SECONDS))


async def _execute_monitor(monitor: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    monitor_type = str(monitor.get("type") or "")
    target = str(monitor.get("target") or "")
    status = "failed"
    http_status: int | None = None
    summary: str

    try:
        if monitor_type not in {"web", "api", "mcp"}:
            raise ValueError(f"monitor type {monitor_type!r} has no bounded executor")
        result = await health_check(target, timeout=_timeout_for(monitor))
        http_status = result.status_code
        if result.ok:
            status = "healthy"
            summary = f"HTTP {http_status}" if http_status is not None else "target healthy"
        else:
            summary = result.error or (
                f"HTTP {http_status}" if http_status is not None else "target unhealthy"
            )
    except Exception as exc:  # noqa: BLE001 -- execution failures are persisted as data
        summary = f"{type(exc).__name__}: {exc}"

    latency_ms = max(0, round((time.perf_counter() - started) * 1000))
    checked_at = datetime.now(UTC)
    run_id = f"mrun_{uuid.uuid4().hex}"
    summary = summary[:1000]

    with store._connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ih_monitor_runs
                (id, monitor_id, status, latency_ms, http_status, summary, credits_charged)
            VALUES (%s, %s, %s, %s, %s, %s, 0)
            """,
            (run_id, monitor["id"], status, latency_ms, http_status, summary),
        )
        cur.execute(
            """
            UPDATE ih_monitors
            SET last_status=%s, last_checked_at=%s, updated_at=now()
            WHERE id=%s
            """,
            (status, checked_at, monitor["id"]),
        )
        conn.commit()

    return {
        "id": run_id,
        "monitor_id": monitor["id"],
        "status": status,
        "http_status": http_status,
        "latency_ms": latency_ms,
        "summary": summary,
    }


async def run_due_monitors(limit: int = MAX_BATCH) -> dict[str, Any]:
    claimed = _claim_due_monitors(limit)
    runs: list[dict[str, Any]] = []
    for monitor in claimed:
        try:
            runs.append(await _execute_monitor(monitor))
        except Exception as exc:  # noqa: BLE001 -- batch isolation boundary
            runs.append(
                {
                    "monitor_id": monitor.get("id"),
                    "status": "executor_error",
                    "summary": f"{type(exc).__name__}: {exc}"[:1000],
                }
            )
    return {"claimed": len(claimed), "completed": len(runs), "runs": runs}


@router.get("/api/internal/monitors/tick")
async def monitor_tick(authorization: str | None = Header(default=None)):
    """Scheduler entrypoint supporting legacy secret auth and GitHub Actions OIDC."""
    await _scheduler_authorized(authorization)
    return await run_due_monitors()
