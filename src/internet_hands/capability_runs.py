"""Owned durable semantic-capability jobs.

The database is the queue and billing boundary. Provider job identifiers stay private;
callers receive only OpenCrawl run IDs and terminal dataset links.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from .capability_economics import settle_measured_cost
from .control_store import AuthIdentity, ControlError, ControlStore
from .datasets import DatasetStore

TERMINAL = {"completed", "failed", "cancelled"}
MAX_ATTEMPTS = 14

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ih_capability_runs (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
    request_id text NOT NULL UNIQUE REFERENCES ih_usage_events(request_id) ON DELETE CASCADE,
    api_key_id text REFERENCES ih_api_keys(id) ON DELETE SET NULL,
    idempotency_key text NOT NULL,
    fingerprint text NOT NULL,
    capability text NOT NULL,
    arguments jsonb NOT NULL,
    plan_slug text NOT NULL,
    credits_reserved integer NOT NULL,
    credits_charged integer NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'queued'
        CHECK(status IN ('queued','running','waiting','completed','failed','cancelled')),
    attempts integer NOT NULL DEFAULT 0,
    lease_token text,
    lease_until timestamptz,
    next_poll_at timestamptz NOT NULL DEFAULT now(),
    provider text,
    provider_job_id text,
    measured_usage jsonb NOT NULL DEFAULT '{}'::jsonb,
    result_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    dataset_id text REFERENCES ih_datasets(id) ON DELETE SET NULL,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    expires_at timestamptz NOT NULL DEFAULT now()+interval '60 minutes',
    UNIQUE(user_id,idempotency_key)
);
DROP TRIGGER IF EXISTS ih_capability_execution_event ON ih_capability_runs;
CREATE TRIGGER ih_capability_execution_event AFTER INSERT OR UPDATE ON ih_capability_runs
    FOR EACH ROW EXECUTE FUNCTION ih_record_execution_transition();
CREATE INDEX IF NOT EXISTS ih_capability_runs_queue_idx
    ON ih_capability_runs(status,next_poll_at,created_at);
CREATE INDEX IF NOT EXISTS ih_capability_runs_owner_idx
    ON ih_capability_runs(user_id,created_at DESC);
"""


class LostCapabilityLease(Exception):
    """The worker must stop after losing its fenced lease."""


def public_run(row: dict[str, Any]) -> dict[str, Any]:
    arguments = row.get("arguments") or {}
    nested = arguments.get("arguments") or {}
    summary = row.get("result_summary") or {}
    return {
        "id": row.get("id"),
        "request_id": row.get("request_id"),
        "capability": row.get("capability"),
        "status": row.get("status"),
        "attempts": row.get("attempts"),
        "dataset_id": row.get("dataset_id"),
        "credits_reserved": row.get("credits_reserved"),
        "credits_charged": row.get("credits_charged"),
        "error_code": row.get("error_code"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "finished_at": row.get("finished_at"),
        "input": {
            "source_count": len(nested.get("urls") or []),
            "schema_provided": isinstance(nested.get("schema"), dict),
            "effort": nested.get("effort"),
        },
        "result": {
            "record_count": summary.get("record_count", 0),
            "schema_valid": summary.get("schema_valid"),
            "schema_errors": summary.get("schema_errors") or [],
            "source_urls": summary.get("source_urls") or [],
        },
    }


class CapabilityRunStore:
    def __init__(self, control: ControlStore):
        self.control = control

    def ensure_schema(self) -> None:
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(_SCHEMA)
            conn.commit()

    def create(
        self,
        identity: AuthIdentity,
        key: str,
        capability: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
            raise ControlError(
                "idempotency_key_required",
                "Provide an Idempotency-Key (1–128 letters, digits, . _ : -).",
                422,
            )
        payload = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(
            f"{capability}\n{payload}".encode()
        ).hexdigest()
        self.ensure_schema()
        self.control.release_stale_reservations(identity.user_id)
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM ih_users WHERE id=%s FOR UPDATE", (identity.user_id,))
            cur.execute(
                """
                SELECT * FROM ih_capability_runs
                WHERE user_id=%s AND idempotency_key=%s
                """,
                (identity.user_id, key),
            )
            existing = cur.fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise ControlError(
                        "idempotency_conflict",
                        "This key already belongs to different capability inputs.",
                        409,
                    )
                return public_run(dict(existing))

            request_id = "req_" + uuid.uuid4().hex
            run_id = "caprun_" + uuid.uuid4().hex
            reserved = self.control.reserve_tool_call(
                identity=identity,
                request_id=request_id,
                tool_name="mesh_capability_execute",
                arguments=arguments,
                input_bytes=len(payload.encode()),
                transaction=conn,
            )
            cur.execute(
                """
                INSERT INTO ih_capability_runs(
                    id,user_id,request_id,api_key_id,idempotency_key,fingerprint,
                    capability,arguments,plan_slug,credits_reserved
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                RETURNING *
                """,
                (
                    run_id,
                    identity.user_id,
                    request_id,
                    identity.api_key_id,
                    key,
                    fingerprint,
                    capability,
                    payload,
                    identity.plan_slug,
                    reserved,
                ),
            )
            return public_run(dict(cur.fetchone()))

    def get(self, owner: str, run_id: str) -> dict[str, Any]:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM ih_capability_runs WHERE id=%s AND user_id=%s",
                (run_id, owner),
            )
            return public_run(self._owned(cur.fetchone()))

    def list(self, owner: str, limit: int, offset: int) -> dict[str, Any]:
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM ih_capability_runs WHERE user_id=%s",
                (owner,),
            )
            total = int(cur.fetchone()["n"])
            cur.execute(
                """
                SELECT * FROM ih_capability_runs
                WHERE user_id=%s
                ORDER BY created_at DESC,id DESC
                LIMIT %s OFFSET %s
                """,
                (owner, limit, offset),
            )
            return {
                "runs": [public_run(dict(row)) for row in cur.fetchall()],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def cancel(self, owner: str, run_id: str) -> dict[str, Any]:
        """Cancel only work that has not started upstream."""
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM ih_capability_runs
                WHERE id=%s AND user_id=%s
                FOR UPDATE
                """,
                (run_id, owner),
            )
            row = self._owned(cur.fetchone())
            if row["status"] == "queued":
                credits = self.control.settle_tool_call(
                    row["request_id"],
                    status="cancelled",
                    latency_ms=0,
                    output_bytes=0,
                    actual_credits=0,
                    execution_usage={"completed": False},
                    transaction=conn,
                )
                cur.execute(
                    """
                    UPDATE ih_capability_runs
                    SET status='cancelled',credits_charged=%s,finished_at=now(),
                        updated_at=now(),error_code=NULL
                    WHERE id=%s
                    RETURNING *
                    """,
                    (credits, run_id),
                )
                conn.commit()
                return public_run(dict(cur.fetchone()))
            if row["status"] in {"running", "waiting"}:
                raise ControlError(
                    "run_already_started",
                    (
                        "This extraction already started upstream. OpenCrawl does not "
                        "claim cancellation until the provider supports a verified stop."
                    ),
                    409,
                )
            return public_run(dict(row))

    def claim(self, run_id: str | None = None) -> dict[str, Any] | None:
        """Lease one queued launch or due provider-status poll.

        A caller may name a newly created run to launch it immediately. Scheduled
        workers omit run_id and select the oldest eligible global job.
        """
        self.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT *,expires_at<=now() AS expired
                FROM ih_capability_runs
                WHERE (%s::text IS NULL OR id=%s)
                  AND (
                    status='queued'
                    OR (status='waiting' AND next_poll_at<=now())
                    OR (status='running' AND lease_until<=now())
                  )
                ORDER BY next_poll_at,created_at,id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                (run_id, run_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            row = dict(row)

            if row["expired"] or row["attempts"] >= MAX_ATTEMPTS:
                self._finish_without_output(
                    cur,
                    conn,
                    row,
                    "failed",
                    "provider_timeout",
                    row.get("measured_usage") or {},
                    charge_measured=True,
                )
                return {"recovered_terminal": True, "id": row["id"]}

            if row["status"] == "running" and not row.get("provider_job_id"):
                # Launch outcome is unknowable after the lease dies. Replaying can
                # duplicate expensive upstream work, so fail closed and absorb it.
                self._finish_without_output(
                    cur,
                    conn,
                    row,
                    "failed",
                    "launch_outcome_unknown",
                    row.get("measured_usage") or {},
                    charge_measured=False,
                )
                return {"recovered_terminal": True, "id": row["id"]}

            token = uuid.uuid4().hex
            cur.execute(
                """
                UPDATE ih_capability_runs
                SET status='running',attempts=attempts+1,lease_token=%s,
                    lease_until=now()+interval '90 seconds',updated_at=now()
                WHERE id=%s
                RETURNING *
                """,
                (token, row["id"]),
            )
            return dict(cur.fetchone())

    def wait_for_provider(
        self,
        job: dict[str, Any],
        *,
        provider: str,
        provider_job_id: str,
        usage: dict[str, Any],
    ) -> bool:
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ih_capability_runs
                SET status='waiting',provider=%s,provider_job_id=%s,
                    measured_usage=%s::jsonb,next_poll_at=now()+interval '30 seconds',
                    lease_token=NULL,lease_until=NULL,updated_at=now()
                WHERE id=%s AND status='running' AND lease_token=%s
                    AND lease_until>now()
                RETURNING id
                """,
                (
                    provider,
                    provider_job_id,
                    json.dumps(usage),
                    job["id"],
                    job["lease_token"],
                ),
            )
            if not cur.fetchone():
                raise LostCapabilityLease()
            conn.commit()
            return True

    def continue_waiting(
        self,
        job: dict[str, Any],
        *,
        usage: dict[str, Any],
    ) -> bool:
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ih_capability_runs
                SET status='waiting',measured_usage=%s::jsonb,
                    next_poll_at=now()+interval '30 seconds',
                    lease_token=NULL,lease_until=NULL,updated_at=now()
                WHERE id=%s AND status='running' AND lease_token=%s
                    AND lease_until>now()
                RETURNING id
                """,
                (json.dumps(usage), job["id"], job["lease_token"]),
            )
            if not cur.fetchone():
                raise LostCapabilityLease()
            conn.commit()
            return True

    def finish(
        self,
        job: dict[str, Any],
        *,
        status: str,
        result: dict[str, Any],
        usage: dict[str, Any],
        error_code: str | None = None,
    ) -> bool:
        if status not in TERMINAL:
            raise ValueError("A terminal status is required.")
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM ih_capability_runs
                WHERE id=%s AND status='running' AND lease_token=%s
                    AND lease_until>now()
                FOR UPDATE
                """,
                (job["id"], job["lease_token"]),
            )
            row = cur.fetchone()
            if not row:
                return False
            row = dict(row)

            dataset_id = None
            if status == "completed":
                try:
                    saved = DatasetStore(self.control).save(
                        row["user_id"],
                        row["request_id"],
                        "extract",
                        result,
                        result.get("name") or "Structured extraction",
                        transaction=conn,
                    )
                    dataset_id = saved["id"]
                except ControlError as exc:
                    if exc.code != "dataset_too_large":
                        raise
                    status = "failed"
                    error_code = "output_limit_exceeded"

            measured = {**usage, "completed": status == "completed"}
            raw_reserved = self.control.raw_tool_reservation(
                row["request_id"],
                transaction=conn,
            )
            raw_cost = settle_measured_cost(
                "mesh_capability_execute",
                row["arguments"],
                row["plan_slug"],
                reserved_credits=raw_reserved,
                execution_usage=measured,
            )
            output_bytes = (
                len(json.dumps(result, ensure_ascii=False, default=str).encode())
                if result
                else 0
            )
            credits = self.control.settle_tool_call(
                row["request_id"],
                status="ok" if status == "completed" else status,
                latency_ms=int(result.get("duration_ms") or 0),
                output_bytes=output_bytes,
                actual_credits=raw_cost,
                execution_usage=measured,
                transaction=conn,
            )
            summary = {
                "record_count": len(result.get("records") or []),
                "schema_valid": result.get("schema_validation", {}).get("valid"),
                "schema_errors": result.get("schema_validation", {}).get("errors") or [],
                "source_urls": result.get("source_urls") or [],
            }
            cur.execute(
                """
                UPDATE ih_capability_runs
                SET status=%s,credits_charged=%s,dataset_id=%s,
                    measured_usage=%s::jsonb,result_summary=%s::jsonb,
                    error_code=%s,lease_token=NULL,lease_until=NULL,
                    updated_at=now(),finished_at=now()
                WHERE id=%s
                """,
                (
                    status,
                    credits,
                    dataset_id,
                    json.dumps(measured),
                    json.dumps(summary),
                    error_code,
                    row["id"],
                ),
            )
            conn.commit()
            return True

    def fail(
        self,
        job: dict[str, Any],
        *,
        usage: dict[str, Any],
        error_code: str,
        charge_measured: bool = True,
    ) -> bool:
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM ih_capability_runs
                WHERE id=%s AND status='running' AND lease_token=%s
                    AND lease_until>now()
                FOR UPDATE
                """,
                (job["id"], job["lease_token"]),
            )
            row = cur.fetchone()
            if not row:
                return False
            self._finish_without_output(
                cur,
                conn,
                dict(row),
                "failed",
                error_code,
                usage,
                charge_measured=charge_measured,
            )
            return True

    def _finish_without_output(
        self,
        cur,
        conn,
        row: dict[str, Any],
        status: str,
        error_code: str,
        usage: dict[str, Any],
        *,
        charge_measured: bool,
    ) -> None:
        measured = {**usage, "completed": False}
        if charge_measured:
            raw_reserved = self.control.raw_tool_reservation(
                row["request_id"],
                transaction=conn,
            )
            raw_cost = settle_measured_cost(
                "mesh_capability_execute",
                row["arguments"],
                row["plan_slug"],
                reserved_credits=raw_reserved,
                execution_usage=measured,
            )
        else:
            raw_cost = 0
        credits = self.control.settle_tool_call(
            row["request_id"],
            status=status,
            latency_ms=0,
            output_bytes=0,
            actual_credits=raw_cost,
            execution_usage=measured,
            transaction=conn,
        )
        cur.execute(
            """
            UPDATE ih_capability_runs
            SET status=%s,credits_charged=%s,measured_usage=%s::jsonb,
                error_code=%s,lease_token=NULL,lease_until=NULL,
                updated_at=now(),finished_at=now()
            WHERE id=%s
            """,
            (status, credits, json.dumps(measured), error_code, row["id"]),
        )
        conn.commit()

    @staticmethod
    def _owned(row):
        if not row:
            raise ControlError(
                "run_not_found",
                "Capability run not found for this account.",
                404,
            )
        return dict(row)
