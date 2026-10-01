"""Internal provider usage facts; customer credits are never treated as provider COGS."""
from .control_store import ControlError
from .resource_measurements import resource_coverage

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
            cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            cur.execute('''SELECT r.id,u.metadata#>'{measured_usage,provider_calls}' AS provider_calls
                FROM ih_runs r JOIN ih_usage_events u ON u.request_id=r.id WHERE r.id=%s''', (run_id,))
            run=cur.fetchone()
            if not run:
                raise ControlError('run_not_found', 'Run not found.', 404)
            cur.execute('''SELECT count(*) AS event_count,
                count(*) FILTER(WHERE total_cost_usd IS NULL) AS unknown_event_count,
                sum(total_cost_usd) AS known_cost_subtotal_usd,
                count(*) FILTER(WHERE total_cost_usd IS NOT NULL AND NOT estimated) AS legacy_valued_count
                FROM ih_cost_events WHERE run_id=%s''', (run_id,))
            summary = dict(cur.fetchone())
            cur.execute("""SELECT count(*) FILTER(WHERE measurement_kind='usage') AS usage_record_count,
                count(*) FILTER(WHERE measurement_kind='usage' AND (credits_used IS NULL OR credits_used<0)) AS missing_quantity_count,
                count(*) FILTER(WHERE measurement_kind='unclassified') AS unclassified_record_count
                FROM ih_provider_usage WHERE request_id=%s""",(run_id,))
            unit_coverage=dict(cur.fetchone())
            cur.execute('SELECT DISTINCT lower(provider) AS provider,operation FROM ih_cost_events WHERE run_id=%s',(run_id,))
            measured_operations={(row['provider'],row['operation']) for row in cur.fetchall()}
            measured_providers={provider for provider, _ in measured_operations}
            expected=run['provider_calls'] if isinstance(run['provider_calls'],dict) else {}
            expected_providers={name.lower() for name, count in expected.items() if type(count) is int and count>0}
            cur.execute("SELECT DISTINCT lower(provider) AS provider,operation FROM ih_provider_usage WHERE request_id=%s AND measurement_kind='attempt'",(run_id,))
            expected_operations={(row['provider'],row['operation']) for row in cur.fetchall()}
            expected_providers.update(provider for provider, _ in expected_operations)
            unit_coverage['missing_provider_count']=len(expected_providers-measured_providers)
            unit_coverage['missing_operation_count']=len(expected_operations-measured_operations)
            unit_coverage['measured_record_count']=summary['event_count']
            quantity_complete=bool(summary['event_count']) and not any(unit_coverage[name] for name in
                ('missing_quantity_count','unclassified_record_count','missing_provider_count','missing_operation_count'))
            unit_coverage['state']='reported_records_measured' if quantity_complete else 'incomplete'
            incomplete = not quantity_complete or summary['unknown_event_count']>0
            summary['provider_unit_valuation_state'] = 'unknown' if incomplete else 'valued'
            summary['cost_state'] = 'unknown'
            summary['coverage'] = 'partial'
            summary['provider_cost_total_usd'] = None if incomplete else summary['known_cost_subtotal_usd']
            summary['total_cost_usd'] = None
            cur.execute('''SELECT id,provider,operation,cost_type,quantity,unit,unit_cost_usd,total_cost_usd,rate_revision,
                source,valuation_source,estimated,created_at FROM ih_cost_events WHERE run_id=%s
                ORDER BY created_at,id LIMIT %s OFFSET %s''', (run_id,limit,offset))
            events=[dict(row) for row in cur.fetchall()]
            cur.execute('SELECT dimension,unit,quantity,source FROM ih_run_cost_measurements WHERE run_id=%s',(run_id,))
            measurements=[dict(row) for row in cur.fetchall()]
            coverage={name:{'state':'not_instrumented'} for name in ('browser','model','compute','storage','delivery','proxy')}
            coverage['provider_units']=unit_coverage
            for measurement in measurements:
                dimension = measurement['dimension']
                if dimension in coverage:
                    group = coverage[dimension]
                    group.update(state='partial', valuation_state='unknown')
                    group.setdefault('measurements', []).append(measurement)
            coverage.update(resource_coverage(cur, run_id))
            summary['valuation_kind']=('mixed_or_legacy' if summary['legacy_valued_count'] else 'rate_estimate') if not incomplete else 'incomplete'
            cur.execute('''SELECT reason,count(*) AS count FROM (SELECT CASE
                WHEN EXISTS(SELECT 1 FROM ih_cost_rates r WHERE r.provider=lower(c.provider)
                    AND r.operation=c.operation AND r.unit=c.unit AND r.effective_from<=c.created_at AND c.created_at<r.effective_until)
                    THEN 'valuation_required'
                WHEN EXISTS(SELECT 1 FROM ih_cost_rates r WHERE r.provider=lower(c.provider)
                    AND r.operation=c.operation AND r.unit=c.unit) THEN 'outside_validity_window'
                ELSE 'missing_rate' END AS reason FROM ih_cost_events c
                WHERE c.run_id=%s AND c.unit_cost_usd IS NULL) unpriced GROUP BY reason''',(run_id,))
            summary['unpriced_reason_counts']={row['reason']:row['count'] for row in cur.fetchall()}
            return {'run_id':run_id,'summary':summary,'events':events,'coverage':coverage,
                    'limit':limit,'offset':offset}
