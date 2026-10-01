"""Canonical owned run receipts. Billing remains owned by the usage ledger."""
from __future__ import annotations

from .control_store import ControlError

SCHEMA = """
CREATE TABLE IF NOT EXISTS ih_runs (
 id text PRIMARY KEY REFERENCES ih_usage_events(request_id) ON DELETE CASCADE,
 user_id text NOT NULL REFERENCES ih_users(id) ON DELETE CASCADE,
 capability_id text,
 status text NOT NULL,
 api_key_id text,
 credits_reserved integer NOT NULL DEFAULT 0,
 credits_charged integer NOT NULL DEFAULT 0,
 quote_revision text,
 created_at timestamptz NOT NULL,
 finished_at timestamptz,
 event_sequence bigint NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ih_runs_owner_idx ON ih_runs(user_id,created_at DESC,id);
CREATE TABLE IF NOT EXISTS ih_run_events (
 run_id text NOT NULL REFERENCES ih_runs(id) ON DELETE CASCADE,
 sequence bigint NOT NULL,
 timestamp timestamptz NOT NULL DEFAULT now(),
 type text NOT NULL,
 status text NOT NULL,
 attempt integer,
 PRIMARY KEY(run_id,sequence)
);
ALTER TABLE ih_run_events ADD COLUMN IF NOT EXISTS attempt integer;
CREATE OR REPLACE FUNCTION ih_sync_run_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE seq bigint;
BEGIN
 INSERT INTO ih_runs(id,user_id,capability_id,status,api_key_id,credits_reserved,
 credits_charged,quote_revision,created_at,finished_at)
 VALUES(NEW.request_id,NEW.user_id,COALESCE(NEW.capability,NEW.tool_ref),NEW.status,
 NEW.api_key_id,COALESCE((NEW.metadata->'reservation'->>'reserved')::integer,
 (NEW.metadata->'reservation'->>'credits')::integer,0),
 NEW.credits_charged,NEW.metadata->'budget'->>'quote_revision',NEW.created_at,
 CASE WHEN NEW.status='reserved' THEN NULL ELSE now() END)
 ON CONFLICT(id) DO UPDATE SET status=EXCLUDED.status,
 credits_reserved=EXCLUDED.credits_reserved,credits_charged=EXCLUDED.credits_charged,
 finished_at=EXCLUDED.finished_at;
 IF TG_OP='INSERT' THEN
  UPDATE ih_runs SET event_sequence=event_sequence+1 WHERE id=NEW.request_id
  RETURNING event_sequence INTO seq;
  INSERT INTO ih_run_events(run_id,sequence,type,status)
  VALUES(NEW.request_id,seq,CASE WHEN NEW.status='reserved'
 THEN 'reservation_recorded' ELSE 'receipt_recorded' END,NEW.status);
 ELSIF OLD.status IS DISTINCT FROM NEW.status OR
       OLD.credits_charged IS DISTINCT FROM NEW.credits_charged THEN
  UPDATE ih_runs SET event_sequence=event_sequence+1 WHERE id=NEW.request_id
  RETURNING event_sequence INTO seq;
  INSERT INTO ih_run_events(run_id,sequence,type,status)
  VALUES(NEW.request_id,seq,'billing_transition',NEW.status);
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ih_run_receipt_trigger ON ih_usage_events;
CREATE TRIGGER ih_run_receipt_trigger AFTER INSERT OR UPDATE ON ih_usage_events
 FOR EACH ROW EXECUTE FUNCTION ih_sync_run_receipt();
CREATE OR REPLACE FUNCTION ih_record_execution_transition() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE seq bigint; event_type text; current_row jsonb; prior_row jsonb;
BEGIN
 current_row := to_jsonb(NEW);
 IF TG_OP='INSERT' THEN
  event_type := 'execution_created';
 ELSE
  prior_row := to_jsonb(OLD);
  IF prior_row->>'status' IS DISTINCT FROM current_row->>'status' THEN
   event_type := 'execution_status';
  ELSIF prior_row->>'attempts' IS DISTINCT FROM current_row->>'attempts' THEN
   event_type := 'execution_attempt';
  ELSIF prior_row->>'cancel_requested' IS DISTINCT FROM current_row->>'cancel_requested' THEN
   event_type := 'cancellation_requested';
  ELSE
   RETURN NEW;
  END IF;
 END IF;
 UPDATE ih_runs SET event_sequence=event_sequence+1 WHERE id=NEW.request_id
 RETURNING event_sequence INTO seq;
 IF seq IS NOT NULL THEN
  INSERT INTO ih_run_events(run_id,sequence,type,status,attempt)
  VALUES(NEW.request_id,seq,event_type,NEW.status,NEW.attempts);
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ih_crawl_execution_event ON ih_crawl_runs;
CREATE TRIGGER ih_crawl_execution_event AFTER INSERT OR UPDATE ON ih_crawl_runs
 FOR EACH ROW EXECUTE FUNCTION ih_record_execution_transition();
INSERT INTO ih_runs(id,user_id,capability_id,status,api_key_id,credits_reserved,
 credits_charged,quote_revision,created_at)
 SELECT request_id,user_id,COALESCE(capability,tool_ref),status,api_key_id,
 COALESCE((metadata->'reservation'->>'reserved')::integer,
 (metadata->'reservation'->>'credits')::integer,0),credits_charged,
 metadata->'budget'->>'quote_revision',created_at FROM ih_usage_events
 ON CONFLICT(id) DO NOTHING;
"""


class RunEnvelopeStore:
    def __init__(self, control):
        self.control = control

    def list(self, owner, limit, offset):
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) AS total FROM ih_runs WHERE user_id=%s", (owner,))
            total = cur.fetchone()["total"]
            cur.execute("""SELECT id,capability_id,status,credits_reserved,credits_charged,
                quote_revision,created_at,finished_at FROM ih_runs WHERE user_id=%s
                ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s""", (owner, limit, offset))
            return {"runs": [dict(row) for row in cur.fetchall()], "total": total}

    def get(self, owner, run_id, after, limit):
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id,capability_id,status,credits_reserved,credits_charged,
                quote_revision,created_at,finished_at FROM ih_runs WHERE id=%s AND user_id=%s""",
                (run_id, owner))
            row = cur.fetchone()
            if not row:
                raise ControlError("run_not_found", "Run not found for this account.", 404)
            run = dict(row)
            cur.execute("""SELECT id,status,attempts,cancel_requested,monitor_id,dataset_id,
                finished_at,error_code FROM ih_crawl_runs WHERE request_id=%s AND user_id=%s""",
                (run_id, owner))
            crawl = cur.fetchone()
            if crawl:
                run["execution"] = dict(crawl) | {"source_kind": "crawl"}
            cur.execute("SELECT to_regclass('ih_capability_runs') AS table_name")
            if cur.fetchone()["table_name"]:
                cur.execute("""SELECT id,status,attempts,dataset_id,finished_at,error_code
                    FROM ih_capability_runs WHERE request_id=%s AND user_id=%s""",
                    (run_id, owner))
                capability = cur.fetchone()
                if capability:
                    run["execution"] = dict(capability) | {"source_kind": "capability"}
            cur.execute("SELECT id FROM ih_datasets WHERE request_id=%s AND user_id=%s", (run_id, owner))
            dataset = cur.fetchone()
            run["output_dataset_id"] = dataset["id"] if dataset else None
            cur.execute("""SELECT sequence,timestamp,type,status,attempt FROM ih_run_events
                WHERE run_id=%s AND sequence>%s ORDER BY sequence LIMIT %s""",
                (run_id, after, limit))
            events = [dict(event) for event in cur.fetchall()]
            return {"run": run, "events": events,
                    "next_after": events[-1]["sequence"] if events else after}
