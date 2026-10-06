"""Execution fields and sanitized events layered over the billing receipt.

Specialized stores remain authoritative. All projections share their transaction.
"""
SCHEMA = """
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1;
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS execution_status text NOT NULL DEFAULT 'created';
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS source_kind text NOT NULL DEFAULT 'usage';
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS source_ref text;
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS monitor_id text;
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS parent_run_id text REFERENCES ih_runs(id) ON DELETE SET NULL;
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS workflow_run_id text;
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS live_dataset_id text;
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS output_dataset_id text REFERENCES ih_datasets(id) ON DELETE SET NULL;
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS source_count integer;
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS started_at timestamptz;
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS duration_ms integer;
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS execution_finished_at timestamptz;
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS retry_count integer NOT NULL DEFAULT 0;
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS warning_count integer NOT NULL DEFAULT 0;
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS cancel_requested boolean NOT NULL DEFAULT false;
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS error_code text;
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS history_origin text NOT NULL DEFAULT 'snapshot';
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS estimated_cost_internal numeric;
ALTER TABLE ih_runs ADD COLUMN IF NOT EXISTS actual_cost_internal numeric;
ALTER TABLE ih_run_events ADD COLUMN IF NOT EXISTS message text;
CREATE INDEX IF NOT EXISTS ih_runs_source_idx ON ih_runs(user_id,source_ref);

CREATE OR REPLACE FUNCTION ih_run_status(s text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
 SELECT CASE s WHEN 'reserved' THEN 'created' WHEN 'accepted' THEN 'queued'
 WHEN 'ok' THEN 'completed' WHEN 'completed' THEN 'completed'
 WHEN 'partial' THEN 'partial' WHEN 'queued' THEN 'queued' WHEN 'running' THEN 'running'
 WHEN 'waiting' THEN 'waiting' WHEN 'cancelled' THEN 'cancelled' ELSE 'failed' END
$$;

CREATE OR REPLACE FUNCTION ih_project_run_usage() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 UPDATE ih_runs SET duration_ms=NEW.latency_ms WHERE id=NEW.request_id;
 UPDATE ih_runs SET execution_status=ih_run_status(NEW.status),
   execution_finished_at=CASE WHEN NEW.status IN ('reserved','accepted') THEN NULL ELSE now() END
 WHERE id=NEW.request_id AND source_kind='usage';
 IF TG_OP='INSERT' THEN
   UPDATE ih_runs SET history_origin='observed',
     source_count=(NEW.metadata#>>'{run,source_count}')::integer WHERE id=NEW.request_id;
 END IF;
 RETURN NEW;
END $$;
-- Alphabetic ordering puts this after the existing billing receipt trigger.
DROP TRIGGER IF EXISTS ih_z_run_usage_projection ON ih_usage_events;
CREATE TRIGGER ih_z_run_usage_projection AFTER INSERT OR UPDATE ON ih_usage_events
 FOR EACH ROW EXECUTE FUNCTION ih_project_run_usage();

CREATE OR REPLACE FUNCTION ih_record_execution_transition() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE seq bigint; event_type text; current_row jsonb; prior_row jsonb; warnings integer; sources integer; partial_output boolean;
BEGIN
 current_row := to_jsonb(NEW);
 warnings := CASE WHEN current_row#>>'{checkpoint,truncated}'='true' THEN 1 ELSE 0 END
   + CASE WHEN COALESCE((current_row#>>'{checkpoint,failed}')::integer,0)>0 THEN 1 ELSE 0 END;
 partial_output := warnings>0;
 IF current_row#>>'{result_summary,schema_valid}'='false' THEN warnings := warnings+1; END IF;
 sources := CASE WHEN TG_TABLE_NAME='ih_crawl_runs' THEN 1
   WHEN jsonb_typeof(current_row#>'{arguments,arguments,urls}')='array'
   THEN jsonb_array_length(current_row#>'{arguments,arguments,urls}') END;
 UPDATE ih_runs SET source_kind=CASE WHEN TG_TABLE_NAME='ih_crawl_runs' THEN 'crawl' ELSE 'capability' END,
   source_ref=NEW.id,execution_status=CASE WHEN NEW.status='completed' AND partial_output THEN 'partial' ELSE ih_run_status(NEW.status) END,
   monitor_id=current_row->>'monitor_id',output_dataset_id=NEW.dataset_id,
   source_count=sources,started_at=CASE WHEN NEW.status='running' THEN COALESCE(started_at,now()) ELSE started_at END,
   execution_finished_at=NEW.finished_at,retry_count=GREATEST(NEW.attempts-1,0),warning_count=warnings,
   cancel_requested=COALESCE((current_row->>'cancel_requested')::boolean,false) OR NEW.status='cancelled',
   error_code=NEW.error_code WHERE id=NEW.request_id;
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
  INSERT INTO ih_run_events(run_id,sequence,type,status,attempt,message)
  VALUES(NEW.request_id,seq,event_type,NEW.status,NEW.attempts,
   CASE WHEN event_type='cancellation_requested' THEN 'Cancellation requested.'
   ELSE 'Execution state: '||NEW.status||'.' END);
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION ih_record_run_output() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE seq bigint;
BEGIN
 UPDATE ih_runs SET output_dataset_id=NEW.id,event_sequence=event_sequence+1 WHERE id=NEW.request_id
 RETURNING event_sequence INTO seq;
 IF seq IS NOT NULL THEN
   INSERT INTO ih_run_events(run_id,sequence,type,status,message)
   SELECT NEW.request_id,seq,'output_saved',execution_status,'Dataset saved.' FROM ih_runs WHERE id=NEW.request_id;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ih_run_output_event ON ih_datasets;
CREATE TRIGGER ih_run_output_event AFTER INSERT ON ih_datasets FOR EACH ROW EXECUTE FUNCTION ih_record_run_output();

CREATE OR REPLACE FUNCTION ih_record_provider_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE seq bigint;
BEGIN
 IF NEW.attempt IS NULL THEN RETURN NEW; END IF;
 UPDATE ih_runs SET event_sequence=event_sequence+1 WHERE id=NEW.request_id RETURNING event_sequence INTO seq;
 IF seq IS NOT NULL THEN
   INSERT INTO ih_run_events(run_id,sequence,type,status,attempt,message)
   VALUES(NEW.request_id,seq,'provider_attempt',
     CASE NEW.status WHEN 'ok' THEN 'completed' WHEN 'error' THEN 'failed' ELSE 'recorded' END,
     NEW.attempt,'Provider attempt recorded.');
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ih_run_provider_event ON ih_provider_usage;
CREATE TRIGGER ih_run_provider_event AFTER INSERT ON ih_provider_usage FOR EACH ROW EXECUTE FUNCTION ih_record_provider_attempt();

-- Historical import: use existing facts, never manufacture a timeline/start time.
UPDATE ih_runs SET execution_status=ih_run_status(status) WHERE source_kind='usage' AND execution_status IS DISTINCT FROM ih_run_status(status);
UPDATE ih_runs r SET source_kind='crawl',source_ref=c.id,execution_status=ih_run_status(c.status),
 monitor_id=c.monitor_id,output_dataset_id=c.dataset_id,source_count=1,
 execution_finished_at=c.finished_at,retry_count=GREATEST(c.attempts-1,0),
 cancel_requested=c.cancel_requested,error_code=c.error_code
 FROM ih_crawl_runs c WHERE r.id=c.request_id AND r.source_kind='usage';
UPDATE ih_runs r SET output_dataset_id=d.id FROM ih_datasets d
 WHERE r.id=d.request_id AND r.output_dataset_id IS NULL;
DO $$ BEGIN
 IF to_regclass('ih_capability_runs') IS NOT NULL THEN
   EXECUTE 'UPDATE ih_runs r SET source_kind=''capability'',source_ref=c.id,execution_status=ih_run_status(c.status),
     output_dataset_id=c.dataset_id,execution_finished_at=c.finished_at,retry_count=GREATEST(c.attempts-1,0),
     error_code=c.error_code FROM ih_capability_runs c WHERE r.id=c.request_id AND r.source_kind=''usage''';
 END IF;
END $$;
"""

PUBLIC_COLUMNS = """id,capability_id,status,credits_reserved,credits_charged,quote_revision,
created_at,finished_at,version,execution_status,source_kind,source_ref,monitor_id,parent_run_id,
workflow_run_id,live_dataset_id,output_dataset_id,source_count,started_at,execution_finished_at,
duration_ms,retry_count,warning_count,cancel_requested,error_code,history_origin"""


def input_summary(arguments):
    """Only counts; raw queries, URLs and authentication material never enter receipts."""
    arguments = arguments if isinstance(arguments, dict) else {}
    nested = arguments.get('arguments') if isinstance(arguments.get('arguments'), dict) else arguments
    urls = nested.get('urls')
    count = len(urls) if isinstance(urls, list) else (1 if nested.get('url') else None)
    return {'source_count':count}
