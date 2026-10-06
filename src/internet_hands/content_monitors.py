"""Schedule owned one-page captures and atomically publish content changes."""
from __future__ import annotations

import hashlib
import json
import uuid

from .capability_economics import settle_measured_cost
from .control_store import ControlError
from .datasets import DatasetStore


def content_identity(control, owner: str, config: dict):
    key_id = config.get("api_key_id")
    identity = control.api_key_identity_for_user(owner, key_id) if isinstance(key_id, str) else None
    if not identity or not ({"*", "mcp:execute"} & set(identity.scopes)):
        raise ControlError("monitor_key_unavailable", "Select an active owned API key with mcp:execute scope.", 403)
    return identity


def content_arguments(target: str) -> dict:
    return {"url": target, "max_pages": 1, "max_depth": 0, "concurrency": 1,
            "max_seconds": 25, "include_content": True, "include_subdomains": False,
            "preserve_query": True, "max_content_bytes_per_page": 50_000, "max_content_bytes": 50_000}


def product_arguments(target: str, maximum=None) -> dict:
    arguments = {**content_arguments(target), "include_content": False, "include_products": True}
    if maximum is not None:
        arguments["max_charge_credits"] = maximum
    return arguments


def queue_due_content_checks(control, limit: int = 1) -> dict:
    """Claim a schedule slot and reserve its durable job in the same transaction."""
    from .crawl_runs import RunStore
    control.ensure_schema()
    queued, blocked = 0, 0
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT m.* FROM ih_monitors m
            WHERE m.type IN ('content','product') AND m.enabled=true
              AND (m.next_check_at IS NULL OR m.next_check_at<=now())
              AND NOT EXISTS (SELECT 1 FROM ih_crawl_runs r WHERE r.monitor_id=m.id AND r.status IN ('queued','running'))
            ORDER BY m.next_check_at NULLS FIRST,m.created_at
            FOR UPDATE OF m SKIP LOCKED LIMIT %s""", (max(1, min(int(limit), 10)),))
        monitors = [dict(row) for row in cur.fetchall()]
        for monitor in monitors:
            try:
                # Savepoint guarantees even a failed reservation leaves no half-job.
                with conn.transaction():
                    identity = content_identity(control, monitor["user_id"], monitor["config"])
                    arguments = (product_arguments(monitor["target"], monitor["config"]["max_charge_credits"])
                                 if monitor["type"] == "product" else content_arguments(monitor["target"]))
                    RunStore(control).create(identity, "monitor:" + uuid.uuid4().hex,
                        arguments, transaction=conn, monitor=monitor)
                queued += 1
                status = "queued"
            except ControlError as exc:
                blocked += 1
                status = "blocked"
                cur.execute("""INSERT INTO ih_monitor_runs(id,monitor_id,status,summary,credits_charged)
                    VALUES (%s,%s,'blocked',%s,0)""", ("mrun_" + uuid.uuid4().hex, monitor["id"], exc.code))
            cur.execute("""UPDATE ih_monitors SET next_check_at=now()+(interval_minutes || ' minutes')::interval,
                last_status=%s,updated_at=now() WHERE id=%s""", (status, monitor["id"]))
    return {"queued": queued, "blocked": blocked}


def content_job_error(control, cur, job: dict) -> str | None:
    # A job can outlive a deleted or edited monitor, but cannot publish its output.
    cur.execute("SELECT * FROM ih_monitors WHERE id=%s AND user_id=%s FOR UPDATE", (job["monitor_id"], job["user_id"]))
    monitor = cur.fetchone()
    if not monitor or monitor["type"] not in {"content", "product"} or monitor["content_version"] != job["monitor_version"]:
        return "monitor_superseded"
    if not monitor["enabled"]:
        return "monitor_paused"
    try:
        content_identity(control, job["user_id"], monitor["config"])
    except ControlError:
        return "monitor_key_unavailable"
    return None


def _fingerprint(page: dict) -> str:
    # Capture timestamps, HTML formatting and whitespace are not content changes.
    canonical = {field: " ".join(str(page.get(field) or "").split()) for field in ("title", "text")}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def finish_content_check(runs, cur, conn, job, status, result, usage, error_code):
    control = runs.control
    stale = content_job_error(control, cur, job)
    cur.execute("SELECT * FROM ih_monitors WHERE id=%s AND user_id=%s", (job["monitor_id"], job["user_id"]))
    monitor = cur.fetchone()
    product_check = bool(job["arguments"].get("include_products"))
    pages = result.get("pages") or []
    page = pages[0] if len(pages) == 1 else {}
    readable = (status == "completed" and 200 <= (page.get("status_code") or 0) < 300
                and not page.get("error") and not page.get("content_error") and bool(page.get("text"))
                and not page.get("content_truncated"))
    if product_check:
        readable = status == "completed" and bool(page.get("products")) and not page.get("product_error")
    dataset_id, diff = None, None
    outcome = "failed"
    if stale or status == "cancelled":
        status, error_code, outcome = "cancelled", stale or error_code, "cancelled"
    elif not readable:
        status, error_code = "failed", error_code or (page.get("product_error") if product_check else None) or "content_unavailable"
    else:
        from .product_data import product_changes, product_fingerprint
        digest = (product_fingerprint(page["products"], monitor["config"]["fields"])
                  if product_check else _fingerprint(page))
        outcome = "baseline" if not monitor["baseline_hash"] else "unchanged" if digest == monitor["baseline_hash"] else "changed"
        if outcome != "unchanged":
            changes = None
            if product_check:
                cur.execute("SELECT rows FROM ih_datasets WHERE id=%s AND user_id=%s",
                            (monitor["baseline_dataset_id"], job["user_id"]))
                previous = cur.fetchone()
                changes = (product_changes(previous["rows"], page["products"], monitor["config"]["fields"])
                           if previous else None)
            output = ({"records": page["products"], "source_urls": [page["url"]], "changes": changes}
                      if product_check else result)
            # No dataset and no dataset.saved webhook for an unchanged check.
            saved = DatasetStore(control).save(job["user_id"], job["request_id"], "product" if product_check else "crawl",
                {**output, "monitor_id": job["monitor_id"], "monitor_status": outcome},
                f'{monitor["name"]}: {outcome}', transaction=conn)
            dataset_id = saved["id"]
            diff = {"previous_dataset_id": monitor["baseline_dataset_id"], "current_dataset_id": dataset_id,
                    "previous_hash": monitor["baseline_hash"], "current_hash": digest}
            if product_check:
                diff["changes"] = changes
            cur.execute("UPDATE ih_monitors SET baseline_hash=%s,baseline_dataset_id=%s WHERE id=%s",
                        (digest, dataset_id, job["monitor_id"]))
    usage = {**usage, "completed": readable and not stale and status == "completed"}
    raw_cost = settle_measured_cost("playground:crawl", job["arguments"], job["plan_slug"],
        reserved_credits=control.raw_tool_reservation(job["request_id"], transaction=conn), execution_usage=usage)
    credits = control.settle_tool_call(job["request_id"], status="ok" if status == "completed" else status,
        latency_ms=int(result.get("duration_ms") or 0), output_bytes=len(json.dumps(result).encode()),
        actual_credits=raw_cost, execution_usage=usage, transaction=conn)
    if monitor:
        summaries = {"baseline": "Readable content baseline saved.", "unchanged": "No readable content change detected.",
                     "changed": "Readable content changed; new capture saved."}
        if product_check:
            summaries = {"baseline": "Product price baseline saved.", "unchanged": "Tracked product fields are unchanged.",
                         "changed": "Tracked product fields changed; new snapshot saved."}
        monitor_run_id = "mrun_" + uuid.uuid4().hex
        cur.execute("""INSERT INTO ih_monitor_runs
            (id,monitor_id,status,latency_ms,http_status,summary,diff,credits_charged,crawl_run_id,dataset_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)""",
            (monitor_run_id, job["monitor_id"], outcome, int(result.get("duration_ms") or 0),
             page.get("status_code"), summaries.get(outcome, error_code or "content_unavailable"),
             json.dumps(diff) if diff else None, credits, job["id"], dataset_id))
        if product_check and outcome == "changed":
            from .monitor_email_store import enqueue_change_email
            enqueue_change_email(cur, monitor, monitor_run_id, dataset_id, diff.get("changes"), page["products"])
        # Superseded output may appear in history, but cannot change the new config's state.
        if monitor["content_version"] == job["monitor_version"]:
            cur.execute("UPDATE ih_monitors SET last_status=%s,last_checked_at=now(),updated_at=now() WHERE id=%s",
                        (outcome, job["monitor_id"]))
    runs._write_terminal(cur, job, status, result, usage, error_code, dataset_id, credits)
