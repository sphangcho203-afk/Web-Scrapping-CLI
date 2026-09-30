"""Execute one bounded job per scheduler request within the serverless budget."""
from __future__ import annotations

import asyncio

from .crawl_frontier import CrawlFrontier
from .crawl_runs import LostLease, RunStore
from .crawler import crawl
from .execution_meter import execution_usage_snapshot, reset_execution_meter, start_execution_meter
from .models import CrawlResult


class RunCancelled(Exception):
    pass


async def dispatch_run(runs: RunStore) -> dict:
    job = await asyncio.to_thread(runs.claim)
    if job is None:
        return {"processed": 0}
    if job.get("recovered_terminal"):
        return {"processed": 1, "recovered": True}
    token = start_execution_meter(job.get("measured_usage"))
    result = job.get("checkpoint") or {}
    status, error_code = "completed", None

    async def progress(snapshot, frontier):
        nonlocal result
        result = snapshot.model_dump(mode="json")
        cancelled = await asyncio.to_thread(runs.checkpoint, job, result, execution_usage_snapshot(),
                                            frontier.model_dump(mode="json"))
        if cancelled:
            raise RunCancelled()

    try:
        resume = None
        if job.get("frontier"):
            resume = (CrawlResult.model_validate(result), CrawlFrontier.model_validate(job["frontier"]))
        # A legacy checkpoint without a frontier restarts from its seed once.
        # New checkpoints carry the original budgets and committed page captures.
        remaining = job["arguments"]["max_seconds"] - (result.get("duration_ms", 0) / 1000 if resume else 0)
        output = await asyncio.wait_for(crawl(job["arguments"]["url"],
            **{key: value for key, value in job["arguments"].items() if key not in {"url", "max_charge_credits", "quote_revision"}},
            respect_robots=True, delay_seconds=0.10, on_checkpoint=progress,
            # The crawler enforces the I/O budget and returns partial captures.
            # Allow it to save that final checkpoint before the worker failsafe.
            resume_checkpoint=resume), timeout=max(0.001, min(50, remaining + 1)))
        result = output.model_dump(mode="json")
    except RunCancelled:
        status = "cancelled"
    except LostLease:
        return {"processed": 0, "lease_lost": True}
    except TimeoutError:
        status, error_code = "failed", "run_timeout"
        result = {**result, "truncated": True}
    except ValueError:
        status, error_code = "failed", "invalid_checkpoint" if job.get("frontier") else "crawl_failed"
    except Exception:  # noqa: BLE001 -- persisted public errors never expose internals
        status = "failed"
        error_code = error_code or "crawl_failed"
    finally:
        usage = execution_usage_snapshot()
        reset_execution_meter(token)
    finished = await asyncio.to_thread(runs.finish, job, status, result, usage, error_code)
    return {"processed": int(finished), "run_id": job["id"]}
