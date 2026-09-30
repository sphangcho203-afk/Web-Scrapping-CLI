"""Execute one bounded job per scheduler request within the serverless budget."""
from __future__ import annotations

import asyncio

from .crawl_runs import LostLease, RunStore
from .crawler import crawl
from .execution_meter import execution_usage_snapshot, reset_execution_meter, start_execution_meter


class RunCancelled(Exception):
    pass


async def dispatch_run(runs: RunStore) -> dict:
    job = await asyncio.to_thread(runs.claim)
    if job is None:
        return {"processed": 0}
    if job.get("recovered_terminal"):
        return {"processed": 1, "recovered": True}
    token = start_execution_meter()
    result = job.get("checkpoint") or {}
    status, error_code = "completed", None

    async def progress(snapshot):
        nonlocal result
        result = snapshot.model_dump(mode="json")
        cancelled = await asyncio.to_thread(runs.checkpoint, job, result, execution_usage_snapshot())
        if cancelled:
            raise RunCancelled()

    try:
        # Restarts use the original bounds and replace checkpoints on each batch.
        # Duplicate recovery work never creates another customer reservation.
        output = await asyncio.wait_for(crawl(job["arguments"]["url"],
            **{key: value for key, value in job["arguments"].items() if key != "url"},
            respect_robots=True, delay_seconds=0.10, on_progress=progress), timeout=50)
        result = output.model_dump(mode="json")
    except RunCancelled:
        status = "cancelled"
    except LostLease:
        return {"processed": 0, "lease_lost": True}
    except TimeoutError:
        status, error_code = "failed", "run_timeout"
        result = {**result, "truncated": True}
    except Exception:  # noqa: BLE001 -- persisted public errors never expose internals
        status, error_code = "failed", "crawl_failed"
    finally:
        usage = execution_usage_snapshot()
        reset_execution_meter(token)
    finished = await asyncio.to_thread(runs.finish, job, status, result, usage, error_code)
    return {"processed": int(finished), "run_id": job["id"]}
