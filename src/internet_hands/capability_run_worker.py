"""Execute one owned semantic-capability job per protected scheduler tick."""
from __future__ import annotations

import asyncio
import math
import time
from typing import Any

from .auth import current_auth
from .capability_runs import CapabilityRunStore, LostCapabilityLease
from .control_store import AuthIdentity
from .execution_meter import execution_usage_snapshot, reset_execution_meter, start_execution_meter
from .tool_mcp import get_capability_registry, get_tool_mesh


def _status(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in {"completed", "success", "succeeded", "done"}:
        return "completed"
    if normalized in {"failed", "error", "cancelled", "canceled"}:
        return "failed"
    return "running"


def _payload(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    for key in ("data", "result", "output"):
        if key in value and value[key] is not None:
            return value[key]
    return value


def _records(value: Any) -> list[dict[str, Any]]:
    candidate = value
    if isinstance(candidate, dict):
        for key in ("records", "items", "results"):
            nested = candidate.get(key)
            if isinstance(nested, list):
                candidate = nested
                break
    if isinstance(candidate, list):
        return [
            dict(item) if isinstance(item, dict) else {"value": item}
            for item in candidate[:1000]
        ]
    if isinstance(candidate, dict):
        return [dict(candidate)]
    return [{"value": candidate}]


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def validate_schema(value: Any, schema: dict[str, Any] | None) -> dict[str, Any]:
    """Validate the useful JSON-Schema subset accepted by the product form."""
    if not schema:
        return {"valid": None, "errors": []}

    errors: list[str] = []

    def visit(current: Any, rule: Any, path: str, depth: int) -> None:
        if len(errors) >= 20:
            return
        if depth > 12 or not isinstance(rule, dict):
            return
        expected = rule.get("type")
        expected_types = (
            [expected]
            if isinstance(expected, str)
            else [item for item in expected or [] if isinstance(item, str)]
        )
        if expected_types and not any(_type_matches(current, item) for item in expected_types):
            errors.append(f"{path}: expected {' or '.join(expected_types)}")
            return
        if "enum" in rule and isinstance(rule["enum"], list) and current not in rule["enum"]:
            errors.append(f"{path}: value is outside the declared enum")
        if isinstance(current, dict):
            required = rule.get("required") or []
            if isinstance(required, list):
                for key in required:
                    if isinstance(key, str) and key not in current:
                        errors.append(f"{path}.{key}: required field is missing")
                        if len(errors) >= 20:
                            return
            properties = rule.get("properties") or {}
            if isinstance(properties, dict):
                for key, child in properties.items():
                    if key in current:
                        visit(current[key], child, f"{path}.{key}", depth + 1)
        if isinstance(current, list) and isinstance(rule.get("items"), dict):
            for index, item in enumerate(current[:1000]):
                visit(item, rule["items"], f"{path}[{index}]", depth + 1)
                if len(errors) >= 20:
                    return

    visit(value, schema, "$", 0)
    return {"valid": not errors, "errors": errors}


def _reported_credits(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("creditsUsed")
    if value is None:
        value = payload.get("credits_used")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return max(0, math.ceil(value))
    return None


def _normalize_result(job: dict[str, Any], payload: Any, duration_ms: int) -> dict[str, Any]:
    arguments = (job.get("arguments") or {}).get("arguments") or {}
    data = _payload(payload)
    validation = validate_schema(data, arguments.get("schema"))
    return {
        "name": "Structured extraction",
        "records": _records(data),
        "structured": data,
        "source_urls": list(arguments.get("urls") or []),
        "schema_validation": validation,
        "duration_ms": max(0, int(duration_ms)),
    }


def _identity(job: dict[str, Any]) -> AuthIdentity:
    return AuthIdentity(
        user_id=job["user_id"],
        api_key_id=job.get("api_key_id"),
        scopes=["mcp:execute"],
        plan_slug=job["plan_slug"],
        rpm_limit=1000,
        source="capability_worker",
        concurrent_limit=1,
    )


async def dispatch_capability_run(
    runs: CapabilityRunStore, run_id: str | None = None
) -> dict[str, Any]:
    job = await asyncio.to_thread(runs.claim, run_id)
    if job is None:
        return {"processed": 0}
    if job.get("recovered_terminal"):
        return {"processed": 1, "recovered": True, "run_id": job["id"]}

    meter = start_execution_meter(job.get("measured_usage") or {})
    auth_token = current_auth.set(_identity(job))
    started = time.monotonic()
    try:
        if not job.get("provider_job_id"):
            arguments = (job.get("arguments") or {}).get("arguments") or {}
            result = await get_capability_registry().execute(
                job["capability"],
                dict(arguments),
                wait_seconds=0,
                timeout_seconds=45,
            )
            execution = result.get("execution") or {}
            state = _status(execution.get("status"))
            usage = execution_usage_snapshot()
            if state == "running":
                # Firecrawl records maxCredits when an async agent is launched.
                # That is reservation headroom, not measured consumption. Remove
                # it until a terminal status reports creditsUsed.
                counters = dict(usage.get("counters") or {})
                counters.pop("firecrawl_work_units", None)
                usage["counters"] = counters
            if state == "failed" or not execution:
                await asyncio.to_thread(
                    runs.fail,
                    job,
                    usage=usage,
                    error_code="provider_launch_failed",
                    charge_measured=True,
                )
                return {"processed": 1, "run_id": job["id"], "status": "failed"}
            if state == "completed":
                normalized = _normalize_result(
                    job,
                    execution.get("data"),
                    int((time.monotonic() - started) * 1000),
                )
                await asyncio.to_thread(
                    runs.finish,
                    job,
                    status="completed",
                    result=normalized,
                    usage=usage,
                )
                return {"processed": 1, "run_id": job["id"], "status": "completed"}

            provider_job_id = str(execution.get("job_id") or "").strip()
            selected = str(result.get("selected") or "").strip()
            provider = selected.split(":", 1)[0] if ":" in selected else ""
            if not provider_job_id or not provider:
                await asyncio.to_thread(
                    runs.fail,
                    job,
                    usage=usage,
                    error_code="provider_job_missing",
                    charge_measured=True,
                )
                return {"processed": 1, "run_id": job["id"], "status": "failed"}
            await asyncio.to_thread(
                runs.wait_for_provider,
                job,
                provider=provider,
                provider_job_id=provider_job_id,
                usage=usage,
            )
            return {"processed": 1, "run_id": job["id"], "status": "waiting"}

        provider = str(job.get("provider") or "")
        provider_job_id = str(job.get("provider_job_id") or "")
        status_payload = await get_tool_mesh().job_status(
            provider,
            provider_job_id,
            wait_seconds=0,
        )
        state = _status(
            status_payload.get("meshStatus")
            if isinstance(status_payload, dict)
            else None
        )
        if state == "running" and isinstance(status_payload, dict):
            state = _status(status_payload.get("status"))

        usage = execution_usage_snapshot()
        reported = _reported_credits(status_payload)
        if reported is not None and provider.casefold() == "firecrawl":
            counters = dict(usage.get("counters") or {})
            counters["firecrawl_work_units"] = reported
            usage["counters"] = counters

        if state == "running":
            await asyncio.to_thread(runs.continue_waiting, job, usage=usage)
            return {"processed": 1, "run_id": job["id"], "status": "waiting"}

        if state == "failed":
            await asyncio.to_thread(
                runs.fail,
                job,
                usage=usage,
                error_code="provider_failed",
                charge_measured=True,
            )
            return {"processed": 1, "run_id": job["id"], "status": "failed"}

        normalized = _normalize_result(
            job,
            status_payload,
            int((time.monotonic() - started) * 1000),
        )
        await asyncio.to_thread(
            runs.finish,
            job,
            status="completed",
            result=normalized,
            usage=usage,
        )
        return {"processed": 1, "run_id": job["id"], "status": "completed"}
    except LostCapabilityLease:
        return {"processed": 0, "lease_lost": True, "run_id": job["id"]}
    except (
        LookupError,
        OSError,
        PermissionError,
        RuntimeError,
        TimeoutError,
        TypeError,
        ValueError,
    ):
        usage = execution_usage_snapshot()
        await asyncio.to_thread(
            runs.fail,
            job,
            usage=usage,
            error_code="worker_failed",
            charge_measured=bool(job.get("provider_job_id")),
        )
        return {"processed": 1, "run_id": job["id"], "status": "failed"}
    finally:
        current_auth.reset(auth_token)
        reset_execution_meter(meter)
