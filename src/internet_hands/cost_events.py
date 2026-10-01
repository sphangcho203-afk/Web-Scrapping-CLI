"""Internal provider usage facts; customer credits are never treated as provider COGS."""
from .control_store import ControlError

SCHEMA = """
CREATE TABLE IF NOT EXISTS ih_cost_events (
    id text PRIMARY KEY REFERENCES ih_provider_usage(id) ON DELETE CASCADE,
    run_id text NOT NULL REFERENCES ih_runs(id) ON DELETE CASCADE,
    provider text NOT NULL,
    cost_type text NOT NULL,
    quantity numeric NOT NULL CHECK(quantity>=0),
    unit text NOT NULL,
    unit_cost_usd numeric CHECK(unit_cost_usd>=0),
    total_cost_usd numeric GENERATED ALWAYS AS (quantity*unit_cost_usd) STORED,
    source text NOT NULL,
    valuation_source text,
    estimated boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK(unit_cost_usd IS NULL OR valuation_source IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ih_cost_events_run_idx ON ih_cost_events(run_id,created_at,id);
CREATE OR REPLACE FUNCTION ih_record_measured_provider_units() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.credits_used IS NOT NULL AND NEW.credits_used>=0 THEN
        INSERT INTO ih_cost_events(id,run_id,provider,cost_type,quantity,unit,source,created_at)
        SELECT NEW.id,NEW.request_id,NEW.provider,'provider_usage',NEW.credits_used,'provider_credit',
            'provider_reported',NEW.created_at FROM ih_runs WHERE id=NEW.request_id
        ON CONFLICT(id) DO NOTHING;
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ih_provider_cost_event ON ih_provider_usage;
CREATE TRIGGER ih_provider_cost_event AFTER INSERT ON ih_provider_usage
    FOR EACH ROW EXECUTE FUNCTION ih_record_measured_provider_units();
INSERT INTO ih_cost_events(id,run_id,provider,cost_type,quantity,unit,source,created_at)
SELECT p.id,p.request_id,p.provider,'provider_usage',p.credits_used,'provider_credit',
    'provider_reported',p.created_at FROM ih_provider_usage p JOIN ih_runs r ON r.id=p.request_id
WHERE p.credits_used IS NOT NULL AND p.credits_used>=0 ON CONFLICT(id) DO NOTHING;
"""


class CostEventStore:
    def __init__(self, control):
        self.control = control

    def for_run(self, run_id, limit, offset):
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT id FROM ih_runs WHERE id=%s', (run_id,))
            if not cur.fetchone():
                raise ControlError('run_not_found', 'Run not found.', 404)
            cur.execute('''SELECT count(*) AS event_count,
                count(*) FILTER(WHERE total_cost_usd IS NULL) AS unknown_event_count,
                sum(total_cost_usd) AS known_cost_subtotal_usd
                FROM ih_cost_events WHERE run_id=%s''', (run_id,))
            summary = dict(cur.fetchone())
            incomplete = not summary['event_count'] or summary['unknown_event_count']>0
            summary['provider_unit_valuation_state'] = 'unknown' if incomplete else 'valued'
            summary['cost_state'] = 'unknown'
            summary['coverage'] = 'provider_units_only'
            summary['provider_cost_total_usd'] = None if incomplete else summary['known_cost_subtotal_usd']
            summary['total_cost_usd'] = None
            cur.execute('''SELECT id,provider,cost_type,quantity,unit,unit_cost_usd,total_cost_usd,
                source,valuation_source,estimated,created_at FROM ih_cost_events WHERE run_id=%s
                ORDER BY created_at,id LIMIT %s OFFSET %s''', (run_id,limit,offset))
            return {'run_id':run_id,'summary':summary,'events':[dict(row) for row in cur.fetchall()],
                    'limit':limit,'offset':offset}
