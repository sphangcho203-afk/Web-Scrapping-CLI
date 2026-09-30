from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from internet_hands import structured_extract_api
from internet_hands.capability_economics import estimate_call
from internet_hands.capability_run_worker import (
    dispatch_capability_run,
    validate_schema,
)
from internet_hands.capability_runs import public_run
from internet_hands.datasets import result_rows


@pytest.mark.asyncio
async def test_extract_arguments_are_bounded_and_hide_provider_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        structured_extract_api,
        "validate_public_http_url",
        lambda value: value,
    )
    metered, product = await structured_extract_api.extract_arguments(
        {
            "urls": [
                "https://example.com/pricing",
                "https://example.com/pricing",
                "https://example.com/features",
            ],
            "prompt": "Extract plan names and monthly prices.",
            "schema": {
                "type": "object",
                "required": ["plans"],
                "properties": {"plans": {"type": "array"}},
            },
            "effort": "low",
        }
    )
    assert metered["capability"] == "web.extract.structured"
    arguments = metered["arguments"]
    assert arguments["urls"] == [
        "https://example.com/pricing",
        "https://example.com/features",
    ]
    assert arguments["zeroDataRetention"] is True
    assert arguments["maxCredits"] == 5
    assert product["source_count"] == 2
    assert "provider" not in product
    assert "maxCredits" not in product

    quote = estimate_call("mesh_capability_execute", metered, "free")
    assert quote.allowed is True
    assert quote.credits > 0


@pytest.mark.asyncio
async def test_extract_rejects_unbounded_or_invalid_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        structured_extract_api,
        "validate_public_http_url",
        lambda value: value,
    )
    with pytest.raises(HTTPException) as missing:
        await structured_extract_api.extract_arguments(
            {"urls": [], "prompt": "Extract pricing"}
        )
    assert missing.value.detail["code"] == "invalid_urls"

    with pytest.raises(HTTPException) as effort:
        await structured_extract_api.extract_arguments(
            {
                "urls": ["https://example.com"],
                "prompt": "Extract pricing",
                "effort": "extreme",
            }
        )
    assert effort.value.detail["code"] == "invalid_effort"

    deep: dict = {}
    cursor = deep
    for _ in range(14):
        cursor["properties"] = {"next": {}}
        cursor = cursor["properties"]["next"]
    with pytest.raises(HTTPException) as schema:
        structured_extract_api._bounded_schema(deep)
    assert schema.value.detail["code"] == "invalid_schema"


def test_schema_validation_never_invents_missing_fields() -> None:
    schema = {
        "type": "object",
        "required": ["company", "price"],
        "properties": {
            "company": {"type": "string"},
            "price": {"type": "number"},
        },
    }
    good = validate_schema({"company": "Acme", "price": 19.0}, schema)
    assert good == {"valid": True, "errors": []}

    missing = validate_schema({"company": "Acme"}, schema)
    assert missing["valid"] is False
    assert any("$.price" in item for item in missing["errors"])


def test_public_capability_run_hides_private_provider_state() -> None:
    row = {
        "id": "caprun_one",
        "request_id": "req_one",
        "capability": "web.extract.structured",
        "status": "waiting",
        "attempts": 2,
        "dataset_id": None,
        "credits_reserved": 300,
        "credits_charged": 0,
        "error_code": None,
        "created_at": None,
        "updated_at": None,
        "finished_at": None,
        "provider": "firecrawl",
        "provider_job_id": "agent:secret-upstream-id",
        "arguments": {
            "capability": "web.extract.structured",
            "arguments": {
                "urls": ["https://example.com"],
                "schema": {"type": "object"},
                "effort": "medium",
            },
        },
        "result_summary": {},
    }
    public = public_run(row)
    assert public["id"] == "caprun_one"
    assert "provider" not in public
    assert "provider_job_id" not in public
    assert "secret-upstream-id" not in str(public)


class _LaunchRegistry:
    async def execute(self, capability, arguments, **kwargs):
        assert capability == "web.extract.structured"
        assert arguments["urls"] == ["https://example.com"]
        assert kwargs["wait_seconds"] == 0
        return {
            "selected": "firecrawl:agent",
            "execution": {
                "status": "running",
                "job_id": "agent:provider-private",
                "data": {"status": "processing"},
            },
        }


class _PollMesh:
    async def job_status(self, provider, job_id, *, wait_seconds=0):
        assert provider == "firecrawl"
        assert job_id == "agent:provider-private"
        assert wait_seconds == 0
        return {
            "status": "completed",
            "meshStatus": "completed",
            "creditsUsed": 3,
            "data": {"company": "Acme", "price": 19},
        }


class _Runs:
    def __init__(self, job):
        self.job = job
        self.waited = None
        self.finished = None
        self.failed = None

    def claim(self, run_id=None):
        if run_id is not None and self.job is not None:
            assert run_id == self.job["id"]
        value, self.job = self.job, None
        return value

    def wait_for_provider(self, job, **kwargs):
        self.waited = (job, kwargs)
        return True

    def continue_waiting(self, job, **kwargs):
        self.waited = (job, kwargs)
        return True

    def finish(self, job, **kwargs):
        self.finished = (job, kwargs)
        return True

    def fail(self, job, **kwargs):
        self.failed = (job, kwargs)
        return True


def _job(*, waiting: bool) -> dict:
    return {
        "id": "caprun_one",
        "user_id": "user_one",
        "api_key_id": "key_one",
        "plan_slug": "free",
        "capability": "web.extract.structured",
        "provider": "firecrawl" if waiting else None,
        "provider_job_id": "agent:provider-private" if waiting else None,
        "measured_usage": (
            {
                "counters": {"firecrawl_work_units": 10},
                "provider_calls": {"firecrawl": 1},
                "provider_events": [],
            }
            if waiting
            else {}
        ),
        "arguments": {
            "capability": "web.extract.structured",
            "arguments": {
                "urls": ["https://example.com"],
                "prompt": "Extract company and price.",
                "effort": "medium",
                "maxCredits": 10,
                "zeroDataRetention": True,
                "schema": {
                    "type": "object",
                    "required": ["company", "price"],
                    "properties": {
                        "company": {"type": "string"},
                        "price": {"type": "number"},
                    },
                },
            },
        },
    }


@pytest.mark.asyncio
async def test_worker_launches_once_then_persists_private_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from internet_hands import capability_run_worker

    runs = _Runs(_job(waiting=False))
    monkeypatch.setattr(
        capability_run_worker,
        "get_capability_registry",
        lambda: _LaunchRegistry(),
    )
    result = await dispatch_capability_run(runs)
    assert result["status"] == "waiting"
    assert runs.failed is None
    assert runs.finished is None
    _job_row, waited = runs.waited
    assert waited["provider"] == "firecrawl"
    assert waited["provider_job_id"] == "agent:provider-private"


@pytest.mark.asyncio
async def test_worker_polls_terminal_result_validates_schema_and_uses_reported_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from internet_hands import capability_run_worker

    runs = _Runs(_job(waiting=True))
    monkeypatch.setattr(
        capability_run_worker,
        "get_tool_mesh",
        lambda: _PollMesh(),
    )
    result = await dispatch_capability_run(runs)
    assert result["status"] == "completed"
    assert runs.failed is None
    _job_row, finished = runs.finished
    extracted = finished["result"]
    assert extracted["records"] == [{"company": "Acme", "price": 19}]
    assert extracted["schema_validation"] == {"valid": True, "errors": []}
    assert extracted["source_urls"] == ["https://example.com"]
    assert finished["usage"]["counters"]["firecrawl_work_units"] == 3


def test_structured_records_are_dataset_compatible() -> None:
    rows = result_rows(
        {
            "records": [
                {"company": "Acme", "price": 19},
                {"company": "Beta", "price": 29},
            ]
        }
    )
    assert len(rows) == 2
    assert rows[0]["record_type"] == "records"


def test_extract_routes_scheduler_and_mount_are_registered() -> None:
    paths = {
        route.path
        for route in structured_extract_api.router.routes
        if hasattr(route, "path")
    }
    assert "/api/extract/quote" in paths
    assert "/api/extract/runs" in paths
    assert "/api/extract/runs/{run_id}" in paths
    assert "/api/extract/runs/{run_id}/cancel" in paths
    assert "/api/internal/capability-runs/tick" in paths

    root = Path(__file__).resolve().parents[1]
    saas = (root / "src" / "internet_hands" / "saas_app.py").read_text(
        encoding="utf-8"
    )
    assert "from .structured_extract_api import router as structured_extract_router" in saas
    assert "app.include_router(structured_extract_router)" in saas

    workflow = (root / ".github" / "workflows" / "monitor-scheduler.yml").read_text(
        encoding="utf-8"
    )
    assert "execute-capability-runs:" in workflow
    assert "/api/internal/capability-runs/tick" in workflow



def test_extract_ui_and_docs_are_productized() -> None:
    import json

    root = Path(__file__).resolve().parents[1]
    web = (root / "web" / "app.js").read_text(encoding="utf-8")
    assert "extract:dashStructuredExtract" in web
    assert "['extract','docs','Structured Extract']" in web
    assert "/api/extract/quote" in web
    assert "/api/extract/runs" in web
    assert "Confirm and start extraction" in web
    assert "provider job identity stays private" in web
    assert "$('[data-open-extract]').forEach" in web
    assert "$$('[data-open-extract]')" not in web

    raw = (root / "web" / "docs-content.js").read_text(encoding="utf-8").strip()
    prefix = "window.OPENCRAWL_DOCS = "
    assert raw.startswith(prefix) and raw.endswith(";")
    docs = json.loads(raw[len(prefix):-1])
    title, group, body = docs["structured-extract"]
    assert title == "Structured Extract"
    assert group == "Collect and use data"
    assert len(body) >= 1800
    assert "/api/extract/quote" in body
    assert "/api/extract/runs" in body
    assert "run_already_started" in body
    assert "measured" in body.casefold()
