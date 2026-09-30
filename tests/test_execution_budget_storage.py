from __future__ import annotations

import pytest
from test_crawl_runs import runs  # noqa: F401 -- shared isolated PostgreSQL fixture

from internet_hands.control_store import ControlError


def test_budget_rejection_is_unbilled_and_settlement_preserves_original_price(request, monkeypatch):
    jobs, identity = request.getfixturevalue("runs")
    control = jobs.control
    monkeypatch.setenv("OPENCRAWL_CREDIT_BURN_MULTIPLIER", "3")
    quote = control.quote_tool_call(identity=identity, tool_name="playground:crawl", arguments={"url": "https://example.com"})
    with pytest.raises(ControlError, match="spending limit"):
        jobs.create(identity, "blocked", {"url": "https://example.com", "max_charge_credits": 0})
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM ih_usage_events WHERE user_id=%s", (identity.user_id,))
        assert cur.fetchone()["n"] == 0
    row = jobs.create(identity, "approved", {"url": "https://example.com",
        "max_charge_credits": quote["credits"], "quote_revision": quote["quote_revision"]})
    assert row["credits_reserved"] == 3
    monkeypatch.setenv("OPENCRAWL_CREDIT_BURN_MULTIPLIER", "7")
    job = jobs.claim()
    output = {"pages": [{"url": "https://example.com", "status_code": 200, "text": "Captured"}]}
    assert jobs.finish(job, "completed", output, {"completed": True})
    final = jobs.get(identity.user_id, row["id"])
    assert final["credits_charged"] == 3
    assert not jobs.finish(job, "completed", output, {"completed": True})
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT monthly_credits,reserved_credits FROM ih_wallets WHERE user_id=%s", (identity.user_id,))
        wallet = cur.fetchone()
        assert wallet["monthly_credits"] == 9997 and wallet["reserved_credits"] == 0


def test_changed_price_requires_a_new_quote_before_job_insertion(request, monkeypatch):
    jobs, identity = request.getfixturevalue("runs")
    monkeypatch.setenv("OPENCRAWL_CREDIT_BURN_MULTIPLIER", "3")
    arguments = {"url": "https://example.com"}
    quote = jobs.control.quote_tool_call(identity=identity, tool_name="playground:crawl", arguments=arguments)
    monkeypatch.setenv("OPENCRAWL_CREDIT_BURN_MULTIPLIER", "2")
    with pytest.raises(ControlError, match="quote"):
        jobs.create(identity, "stale", {**arguments, "max_charge_credits": 100, "quote_revision": quote["quote_revision"]})
    assert jobs.list(identity.user_id, 10, 0)["total"] == 0


async def test_budgeted_worker_executes_without_forwarding_billing_controls(request, monkeypatch):
    from datetime import UTC, datetime
    from urllib.robotparser import RobotFileParser

    from internet_hands import crawler
    from internet_hands.crawl_run_api import crawl_arguments
    from internet_hands.crawl_run_worker import dispatch_run
    from internet_hands.models import FetchResult

    jobs, identity = request.getfixturevalue("runs")
    monkeypatch.setenv("OPENCRAWL_CREDIT_BURN_MULTIPLIER", "3")
    args = crawl_arguments({"url": "https://example.com/", "max_pages": 1, "concurrency": 1})
    quote = jobs.control.quote_tool_call(identity=identity, tool_name="playground:crawl", arguments=args)
    row = jobs.create(identity, "budgeted-worker", {**args, "max_charge_credits": quote["credits"],
                                                  "quote_revision": quote["quote_revision"]})
    calls = []

    async def fetch(url, **kwargs):
        calls.append(url)
        body = "<p>Owned budgeted capture</p>"
        return FetchResult(request_url=url, final_url=url, status_code=200, headers={},
            content_type="text/html", content_length=len(body), sha256="a" * 64,
            elapsed_ms=1, captured_at=datetime.now(UTC), body_text=body)

    async def robots(url):
        parser = RobotFileParser()
        parser.parse(["User-agent: *", "Allow: /"])
        return parser

    monkeypatch.setattr(crawler, "fetch_url", fetch)
    monkeypatch.setattr(crawler, "_robots_for", robots)
    monkeypatch.setattr(crawler, "validate_public_http_url", lambda _: None)
    monkeypatch.setenv("OPENCRAWL_CREDIT_BURN_MULTIPLIER", "7")
    assert (await dispatch_run(jobs))["processed"] == 1
    final = jobs.get(identity.user_id, row["id"])
    assert final["status"] == "completed" and final["credits_charged"] == 3
    assert final["dataset_id"] and calls == ["https://example.com/"]
