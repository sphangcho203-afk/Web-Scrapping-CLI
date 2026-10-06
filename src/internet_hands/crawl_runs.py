"""Owned bounded crawl jobs. The database is the queue and settlement boundary."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from .capability_economics import settle_measured_cost
from .control_store import (
    AuthIdentity,
    ControlError,
    ControlStore,
)
from .datasets import DatasetStore

TERMINAL = {"completed", "failed", "cancelled"}
MAX_ATTEMPTS = 2


def public_run(row: dict) -> dict:
    checkpoint = row.get("checkpoint") or {}
    pages = checkpoint.get("pages") or []
    successful = sum(1 for page in pages if 200 <= (page.get("status_code") or 0) < 300 and not page.get("error"))
    return {key: row.get(key) for key in (
        "id", "request_id", "status", "attempts", "cancel_requested", "dataset_id",
        "credits_reserved", "credits_charged", "error_code", "created_at", "updated_at", "finished_at", "monitor_id",
    )} | {"url": row["arguments"]["url"], "progress": {
        "pages": checkpoint.get("page_count", len(pages)), "discovered_urls": checkpoint.get("discovered_urls", 0),
        "successful": checkpoint.get("successful", successful), "failed": checkpoint.get("failed", len(pages) - successful),
        "truncated": checkpoint.get("truncated", False),
        "frontier_truncated": checkpoint.get("frontier_truncated", False),
        "sitemap_documents": checkpoint.get("sitemap_documents", 0),
        "sitemap_urls": checkpoint.get("sitemap_urls", 0),
        "sitemap_truncated": checkpoint.get("sitemap_truncated", False),
        "sitemap_errors": checkpoint.get("sitemap_error_count", len(checkpoint.get("sitemap_errors") or [])),
    }}


class RunStore:
    def __init__(self, control: ControlStore):
        self.control = control

    def create(self, identity: AuthIdentity, key: str, arguments: dict[str, Any], *,
               transaction=None, monitor: dict | None = None) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
            raise ControlError("idempotency_key_required", "Provide an Idempotency-Key (1–128 letters, digits, . _ : -).", 422)
        payload = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        if transaction is not None:
            return self._create(transaction, identity, key, arguments, payload, fingerprint, monitor)
        self.control.ensure_schema()
        self.control.release_stale_reservations(identity.user_id)
        with self.control._connect() as conn:
            return self._create(conn, identity, key, arguments, payload, fingerprint, monitor)

    def _create(self, conn, identity, key, arguments, payload, fingerprint, monitor):
        with conn.cursor() as cur:
            # Serialize account creates before checking the unique key and wallet.
            cur.execute("SELECT id FROM ih_users WHERE id=%s FOR UPDATE", (identity.user_id,))
            cur.execute("SELECT * FROM ih_crawl_runs WHERE user_id=%s AND idempotency_key=%s", (identity.user_id, key))
            existing = cur.fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise ControlError("idempotency_conflict", "This key already belongs to different crawl inputs.", 409)
                return public_run(existing)
            request_id, run_id = "req_" + uuid.uuid4().hex, "run_" + uuid.uuid4().hex
            reserved = self.control.reserve_tool_call(
                identity=identity, request_id=request_id, tool_name="playground:crawl",
                arguments={**arguments, "monitor_id": monitor["id"]} if monitor else arguments,
                input_bytes=len(payload.encode()), transaction=conn,
            )
            cur.execute("""INSERT INTO ih_crawl_runs
                (id,user_id,request_id,idempotency_key,fingerprint,arguments,plan_slug,credits_reserved,monitor_id,monitor_version)
                VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s) RETURNING *""",
                (run_id, identity.user_id, request_id, key, fingerprint, payload, identity.plan_slug, reserved,
                 monitor["id"] if monitor else None, monitor["content_version"] if monitor else None))
            return public_run(cur.fetchone())

    def get(self, owner: str, run_id: str) -> dict:
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ih_crawl_runs WHERE id=%s AND user_id=%s", (run_id, owner))
            return public_run(self._owned(cur.fetchone()))

    @staticmethod
    def _owned(row):
        if not row:
            raise ControlError("run_not_found", "Run not found for this account.", 404)
        return row

    def list(self, owner: str, limit: int, offset: int) -> dict:
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM ih_crawl_runs WHERE user_id=%s", (owner,))
            total = cur.fetchone()["n"]
            cur.execute("SELECT * FROM ih_crawl_runs WHERE user_id=%s ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s",
                        (owner, limit, offset))
            return {"runs": [public_run(row) for row in cur.fetchall()], "total": total}

    def cancel(self, owner: str, run_id: str) -> dict:
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ih_crawl_runs WHERE id=%s AND user_id=%s FOR UPDATE", (run_id, owner))
            row = self._owned(cur.fetchone())
            if row["status"] == "queued":
                self._finish(cur, conn, row, "cancelled", {}, {}, None)
            elif row["status"] == "running":
                cur.execute("UPDATE ih_crawl_runs SET cancel_requested=true,updated_at=now() WHERE id=%s", (run_id,))
            cur.execute("SELECT * FROM ih_crawl_runs WHERE id=%s", (run_id,))
            return public_run(cur.fetchone())

    def claim(self) -> dict | None:
        """One fenced lease; a dead process is retried once, then terminated."""
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT *,expires_at<=now() AS expired FROM ih_crawl_runs
                WHERE status='queued' OR (status='running' AND lease_until<=now())
                ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1""")
            row = cur.fetchone()
            if not row:
                return None
            if row.get("monitor_id"):
                from .content_monitors import content_job_error
                code = content_job_error(self.control, cur, row)
                if code:
                    self._finish(cur, conn, row, "cancelled", {}, row["measured_usage"], code)
                    return {"recovered_terminal": True, "id": row["id"]}
            if row["cancel_requested"] or row["expired"] or row["attempts"] >= MAX_ATTEMPTS:
                status = "cancelled" if row["cancel_requested"] else "failed"
                code = None if status == "cancelled" else ("run_expired" if row["expired"] else "worker_lost")
                self._finish(cur, conn, row, status, row["checkpoint"], row["measured_usage"], code)
                return {"recovered_terminal": True, "id": row["id"]}
            token = uuid.uuid4().hex
            cur.execute("""UPDATE ih_crawl_runs SET status='running',attempts=attempts+1,
                lease_token=%s,lease_until=now()+interval '90 seconds',updated_at=now()
                WHERE id=%s RETURNING *""", (token, row["id"]))
            return dict(cur.fetchone())

    def checkpoint(self, job: dict, result: dict, usage: dict, frontier: dict | None = None) -> bool:
        """Return cancellation intent; reject expired workers before they can write."""
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE ih_crawl_runs SET checkpoint=%s::jsonb,measured_usage=%s::jsonb,
                frontier=COALESCE(%s::jsonb,frontier),updated_at=now()
                WHERE id=%s AND status='running' AND lease_token=%s AND lease_until>now()
                RETURNING cancel_requested""",
                (json.dumps(result), json.dumps(usage), json.dumps(frontier) if frontier is not None else None,
                 job["id"], job["lease_token"]))
            row = cur.fetchone()
            if not row:
                raise LostLease()
            return row["cancel_requested"]

    def finish(self, job: dict, status: str, result: dict, usage: dict, error_code: str | None = None) -> bool:
        if status not in TERMINAL:
            raise ValueError("A terminal status is required.")
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT * FROM ih_crawl_runs WHERE id=%s AND status='running'
                AND lease_token=%s AND lease_until>now() FOR UPDATE""", (job["id"], job["lease_token"]))
            row = cur.fetchone()
            if not row:
                return False
            if row["cancel_requested"]:
                status, error_code = "cancelled", None
            self._finish(cur, conn, row, status, result, usage, error_code)
            return True

    def _finish(self, cur, conn, row, status, result, usage, error_code):
        if row.get("monitor_id"):
            from .content_monitors import finish_content_check
            finish_content_check(self, cur, conn, row, status, result, usage, error_code)
            return
        # Atomic dataset + outbox + wallet ledger + terminal transition. A rollback
        # leaves the lease recoverable; no half-charged or unsaved successful run.
        dataset_id = None
        pages = result.get("pages") or []
        successful = any(200 <= (page.get("status_code") or 0) < 300 and not page.get("error") for page in pages)
        if status == "completed" and not successful:
            status, error_code = "failed", "no_successful_pages"
        usage = {**usage, "completed": successful}
        if status == "completed" or result.get("pages"):
            try:
                saved = DatasetStore(self.control).save(row["user_id"], row["request_id"], "crawl",
                    {**result, "run_status": status}, row["arguments"]["url"], transaction=conn)
                dataset_id = saved["id"]
            except ControlError as exc:
                if exc.code != "dataset_too_large":
                    raise
                # This validation precedes writes, so settlement can safely close
                # the job without charging for an output we cannot persist.
                status, error_code = "failed", "output_limit_exceeded"
                usage["completed"] = False
        raw_cost = settle_measured_cost("playground:crawl", row["arguments"], row["plan_slug"],
            reserved_credits=self.control.raw_tool_reservation(row["request_id"], transaction=conn), execution_usage=usage)
        credits = self.control.settle_tool_call(row["request_id"], status="ok" if status == "completed" else status,
            latency_ms=int(result.get("duration_ms") or 0), output_bytes=len(json.dumps(result).encode()),
            actual_credits=raw_cost, execution_usage=usage, transaction=conn)
        self._write_terminal(cur, row, status, result, usage, error_code, dataset_id, credits)

    @staticmethod
    def _write_terminal(cur, row, status, result, usage, error_code, dataset_id, credits):
        # Once saved, retain progress only; dataset deletion also removes the run
        # link through its FK and does not leave a second copy of captured text.
        progress = {"page_count": len(result.get("pages") or []),
                    "discovered_urls": result.get("discovered_urls", 0),
                    "truncated": result.get("truncated", False),
                    "frontier_truncated": result.get("frontier_truncated", False),
                    "sitemap_documents": result.get("sitemap_documents", 0),
                    "sitemap_urls": result.get("sitemap_urls", 0),
                    "sitemap_truncated": result.get("sitemap_truncated", False),
                    "sitemap_error_count": len(result.get("sitemap_errors") or [])}
        progress["successful"] = sum(1 for page in result.get("pages") or []
                                     if 200 <= (page.get("status_code") or 0) < 300 and not page.get("error"))
        progress["failed"] = progress["page_count"] - progress["successful"]
        cur.execute("""UPDATE ih_crawl_runs SET status=%s,credits_charged=%s,dataset_id=%s,
            checkpoint=%s::jsonb,frontier='{}'::jsonb,measured_usage=%s::jsonb,error_code=%s,lease_token=NULL,lease_until=NULL,
            updated_at=now(),finished_at=now() WHERE id=%s""",
            (status, credits, dataset_id, json.dumps(progress), json.dumps(usage), error_code, row["id"]))


class LostLease(Exception):
    """A worker must stop when its lease has expired or changed."""
