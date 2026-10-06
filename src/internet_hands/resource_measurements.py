"""Application payload observations, distinct from physical storage or wire egress."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS ih_dataset_payload_measurements (
 dataset_id text PRIMARY KEY,
 run_id text NOT NULL REFERENCES ih_runs(id) ON DELETE CASCADE,
 jsonb_utf8_bytes bigint NOT NULL CHECK(jsonb_utf8_bytes>=0),
 observation_origin text NOT NULL CHECK(observation_origin IN ('insert','existing_snapshot')),
 observed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_dataset_payload_run_idx ON ih_dataset_payload_measurements(run_id);
CREATE OR REPLACE FUNCTION ih_record_dataset_payload() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 INSERT INTO ih_dataset_payload_measurements(dataset_id,run_id,jsonb_utf8_bytes,observation_origin)
 SELECT NEW.id,r.id,octet_length(convert_to(NEW.columns::text,'UTF8'))::bigint
  +octet_length(convert_to(NEW.rows::text,'UTF8'))
  +octet_length(convert_to(NEW.output::text,'UTF8')),'insert'
 FROM ih_runs r WHERE r.id=NEW.request_id ON CONFLICT(dataset_id) DO NOTHING;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ih_dataset_payload_capture ON ih_datasets;
CREATE TRIGGER ih_dataset_payload_capture AFTER INSERT ON ih_datasets
 FOR EACH ROW EXECUTE FUNCTION ih_record_dataset_payload();
INSERT INTO ih_dataset_payload_measurements(dataset_id,run_id,jsonb_utf8_bytes,observation_origin)
SELECT d.id,r.id,octet_length(convert_to(d.columns::text,'UTF8'))::bigint
 +octet_length(convert_to(d.rows::text,'UTF8'))
 +octet_length(convert_to(d.output::text,'UTF8')),'existing_snapshot'
FROM ih_datasets d JOIN ih_runs r ON r.id=d.request_id ON CONFLICT(dataset_id) DO NOTHING;
CREATE OR REPLACE FUNCTION ih_guard_dataset_payload() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Dataset payload observations are immutable';
END $$;
DROP TRIGGER IF EXISTS ih_dataset_payload_guard ON ih_dataset_payload_measurements;
CREATE TRIGGER ih_dataset_payload_guard BEFORE UPDATE ON ih_dataset_payload_measurements
 FOR EACH ROW EXECUTE FUNCTION ih_guard_dataset_payload();

CREATE TABLE IF NOT EXISTS ih_webhook_attempt_measurements (
 delivery_id text NOT NULL,
 lease_token text NOT NULL,
 run_id text NOT NULL REFERENCES ih_runs(id) ON DELETE CASCADE,
 attempt_number integer NOT NULL CHECK(attempt_number>0),
 payload_utf8_bytes bigint NOT NULL CHECK(payload_utf8_bytes>=0),
 claimed_at timestamptz NOT NULL DEFAULT now(),
 dispatch_intent_at timestamptz,
 outcome_recorded_at timestamptz,
 http_status integer CHECK(http_status BETWEEN 100 AND 599),
 outcome text CHECK(outcome IN ('delivered','retry','failed')),
 PRIMARY KEY(delivery_id,lease_token),
 CHECK((outcome_recorded_at IS NULL AND outcome IS NULL AND http_status IS NULL)
  OR (outcome_recorded_at IS NOT NULL AND outcome IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ih_webhook_attempt_run_idx ON ih_webhook_attempt_measurements(run_id);
CREATE OR REPLACE FUNCTION ih_record_webhook_claim() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status='delivering' AND NEW.lease_token IS NOT NULL
    AND NEW.lease_token IS DISTINCT FROM OLD.lease_token THEN
  INSERT INTO ih_webhook_attempt_measurements(delivery_id,lease_token,run_id,attempt_number,payload_utf8_bytes)
  SELECT NEW.id,NEW.lease_token,r.id,NEW.attempts,octet_length(convert_to(NEW.body,'UTF8'))
  FROM ih_datasets d JOIN ih_runs r ON r.id=d.request_id WHERE d.id=NEW.dataset_id
  ON CONFLICT DO NOTHING;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ih_webhook_claim_capture ON ih_dataset_webhook_deliveries;
CREATE TRIGGER ih_webhook_claim_capture AFTER UPDATE OF lease_token ON ih_dataset_webhook_deliveries
 FOR EACH ROW EXECUTE FUNCTION ih_record_webhook_claim();
CREATE OR REPLACE FUNCTION ih_guard_webhook_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF ROW(NEW.delivery_id,NEW.lease_token,NEW.run_id,NEW.attempt_number,NEW.payload_utf8_bytes,NEW.claimed_at)
    IS DISTINCT FROM ROW(OLD.delivery_id,OLD.lease_token,OLD.run_id,OLD.attempt_number,OLD.payload_utf8_bytes,OLD.claimed_at)
    OR (OLD.dispatch_intent_at IS NOT NULL AND NEW.dispatch_intent_at IS DISTINCT FROM OLD.dispatch_intent_at)
    OR (OLD.outcome_recorded_at IS NOT NULL AND ROW(NEW.outcome_recorded_at,NEW.http_status,NEW.outcome,NEW.dispatch_intent_at)
       IS DISTINCT FROM ROW(OLD.outcome_recorded_at,OLD.http_status,OLD.outcome,OLD.dispatch_intent_at)) THEN
  RAISE EXCEPTION 'Webhook attempt evidence cannot be overwritten';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ih_webhook_attempt_guard ON ih_webhook_attempt_measurements;
CREATE TRIGGER ih_webhook_attempt_guard BEFORE UPDATE ON ih_webhook_attempt_measurements
 FOR EACH ROW EXECUTE FUNCTION ih_guard_webhook_attempt();
"""


def resource_coverage(cur, run_id):
    """Bounded aggregates only: never expose payloads, endpoints or lease tokens."""
    cur.execute('''SELECT count(*) AS observed_dataset_count,
        count(*) FILTER(WHERE observation_origin='insert') AS insert_observation_count,
        count(*) FILTER(WHERE observation_origin='existing_snapshot') AS existing_snapshot_count,
        coalesce(sum(jsonb_utf8_bytes),0) AS observed_jsonb_utf8_bytes,
        count(*) FILTER(WHERE EXISTS(SELECT 1 FROM ih_datasets d WHERE d.id=m.dataset_id)) AS current_observed_dataset_count
        FROM ih_dataset_payload_measurements m WHERE run_id=%s''', (run_id,))
    storage = dict(cur.fetchone())
    cur.execute('''SELECT count(*) AS count FROM ih_datasets d WHERE request_id=%s
        AND NOT EXISTS(SELECT 1 FROM ih_dataset_payload_measurements m WHERE m.dataset_id=d.id)''', (run_id,))
    storage['current_dataset_without_measurement_count'] = cur.fetchone()['count']
    storage.update(state='partial', source='postgresql_jsonb_utf8_snapshot', valuation_state='unknown',
                   historical_coverage='not_reconstructed')
    cur.execute('''SELECT count(*) AS claim_count,
        count(dispatch_intent_at) AS dispatch_intent_count,
        count(outcome_recorded_at) AS outcome_count,
        count(*) FILTER(WHERE dispatch_intent_at IS NULL) AS claim_without_intent_count,
        count(*) FILTER(WHERE outcome_recorded_at IS NULL) AS unknown_outcome_count,
        count(*) FILTER(WHERE dispatch_intent_at IS NOT NULL AND outcome_recorded_at IS NULL) AS unfinished_intent_count,
        count(*) FILTER(WHERE outcome='delivered') AS delivered_count,
        count(*) FILTER(WHERE outcome='retry') AS retry_count,
        count(*) FILTER(WHERE outcome='failed') AS failed_count,
        count(*) FILTER(WHERE outcome_recorded_at IS NOT NULL AND http_status IS NULL) AS outcome_without_http_status_count,
        coalesce(sum(payload_utf8_bytes),0) AS claimed_payload_utf8_bytes,
        coalesce(sum(payload_utf8_bytes) FILTER(WHERE dispatch_intent_at IS NOT NULL),0) AS dispatch_intent_payload_utf8_bytes
        FROM ih_webhook_attempt_measurements WHERE run_id=%s''', (run_id,))
    delivery = dict(cur.fetchone())
    cur.execute('''SELECT count(*) AS count FROM ih_dataset_webhook_deliveries w
        JOIN ih_datasets d ON d.id=w.dataset_id WHERE d.request_id=%s
        AND NOT EXISTS(SELECT 1 FROM ih_webhook_attempt_measurements m WHERE m.delivery_id=w.id)''', (run_id,))
    delivery['current_delivery_without_journal_count'] = cur.fetchone()['count']
    delivery.update(state='partial', source='webhook_dispatch_journal', valuation_state='unknown',
                    historical_coverage='not_reconstructed')
    return {'storage': storage, 'delivery': delivery}
