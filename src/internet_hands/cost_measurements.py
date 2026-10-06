"""Measured runtime quantities; a wall-clock duration is not invoiced compute."""
import math

from .provider_cost_reports import normalize_reports


def reported_credit_units(value):
    """Reject malformed telemetry rather than inventing zero or fractional units."""
    if type(value) is int:
        return value if 0 <= value <= 2_147_483_647 else None
    if type(value) is float and math.isfinite(value) and value.is_integer():
        return int(value) if 0 <= value <= 2_147_483_647 else None
    return None


def normalize_provider_units(usage):
    normalized = dict(usage)
    if 'provider_cost_reports' in usage:
        normalized['provider_cost_reports'] = normalize_reports(usage['provider_cost_reports'])
    if 'provider_usage' not in usage:
        return normalized
    normalized['provider_usage'] = [
        {**item, 'credits_used': reported_credit_units(item.get('credits_used'))}
        for item in usage.get('provider_usage') or [] if isinstance(item, dict)
    ]
    return normalized


SCHEMA = """
CREATE TABLE IF NOT EXISTS ih_run_cost_measurements (
 run_id text NOT NULL REFERENCES ih_runs(id) ON DELETE CASCADE,
 dimension text NOT NULL,
 unit text NOT NULL,
 quantity numeric NOT NULL CHECK(quantity>=0),
 source text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(run_id,dimension,unit)
);
CREATE OR REPLACE FUNCTION ih_record_runtime_cost_measurements() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE measured text;
BEGIN
 IF TG_OP='UPDATE' AND OLD.status='reserved' AND NEW.status<>'reserved' THEN
  measured := NEW.metadata#>>'{measured_usage,counters,intelligence_browser_elapsed_ms}';
  IF measured ~ '^[0-9]{1,20}$' THEN
   INSERT INTO ih_run_cost_measurements(run_id,dimension,unit,quantity,source)
   VALUES(NEW.request_id,'browser','elapsed_ms',measured::numeric,'native_playwright_wall_clock')
   ON CONFLICT DO NOTHING;
  END IF;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ih_z_run_runtime_cost_measurements ON ih_usage_events;
CREATE TRIGGER ih_z_run_runtime_cost_measurements AFTER UPDATE ON ih_usage_events
 FOR EACH ROW EXECUTE FUNCTION ih_record_runtime_cost_measurements();
INSERT INTO ih_run_cost_measurements(run_id,dimension,unit,quantity,source,created_at)
SELECT request_id,'browser','elapsed_ms',
 (metadata#>>'{measured_usage,counters,intelligence_browser_elapsed_ms}')::numeric,
 'native_playwright_wall_clock',created_at FROM ih_usage_events
WHERE status<>'reserved' AND metadata#>>'{measured_usage,counters,intelligence_browser_elapsed_ms}' ~ '^[0-9]{1,20}$'
ON CONFLICT DO NOTHING;
"""
