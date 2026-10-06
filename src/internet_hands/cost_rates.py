"""Immutable, sourced provider rates. Valuations are estimates, not invoices."""
import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal, localcontext

from .control_store import ControlError

SCHEMA = """
ALTER TABLE ih_provider_usage ADD COLUMN IF NOT EXISTS measurement_kind text NOT NULL DEFAULT 'unclassified';
UPDATE ih_provider_usage SET measurement_kind=CASE
 WHEN attempt IS NOT NULL OR ref IS NOT NULL THEN 'attempt'
 WHEN credits_used IS NOT NULL THEN 'usage' ELSE 'unclassified' END
 WHERE measurement_kind='unclassified' AND (attempt IS NOT NULL OR ref IS NOT NULL OR credits_used IS NOT NULL);
CREATE TABLE IF NOT EXISTS ih_cost_rates (
 revision text PRIMARY KEY,
 version bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
 provider text NOT NULL,
 operation text NOT NULL,
 unit text NOT NULL CHECK(unit='provider_credit'),
 unit_cost_usd numeric NOT NULL CHECK(unit_cost_usd>=0),
 source_reference text NOT NULL CHECK(length(source_reference) BETWEEN 1 AND 512),
 source_as_of timestamptz NOT NULL,
 effective_from timestamptz NOT NULL,
 effective_until timestamptz NOT NULL CHECK(effective_until>effective_from),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ih_cost_rates_lookup_idx ON ih_cost_rates(provider,operation,unit,version DESC);
ALTER TABLE ih_cost_events ADD COLUMN IF NOT EXISTS operation text;
ALTER TABLE ih_cost_events ADD COLUMN IF NOT EXISTS rate_revision text REFERENCES ih_cost_rates(revision);
UPDATE ih_cost_events c SET operation=p.operation FROM ih_provider_usage p WHERE c.id=p.id AND c.operation IS NULL;

CREATE OR REPLACE FUNCTION ih_immutable_cost_rate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Provider rate revisions are immutable; append a revision.' USING ERRCODE='23514';
END $$;
DROP TRIGGER IF EXISTS ih_cost_rate_immutable ON ih_cost_rates;
CREATE TRIGGER ih_cost_rate_immutable BEFORE UPDATE OR DELETE ON ih_cost_rates
 FOR EACH ROW EXECUTE FUNCTION ih_immutable_cost_rate();

CREATE OR REPLACE FUNCTION ih_pin_provider_cost_rate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE rate ih_cost_rates;
BEGIN
 SELECT operation INTO NEW.operation FROM ih_provider_usage WHERE id=NEW.id;
 SELECT * INTO rate FROM ih_cost_rates WHERE provider=lower(NEW.provider)
  AND operation=NEW.operation AND unit=NEW.unit
  AND effective_from<=NEW.created_at AND NEW.created_at<effective_until
  ORDER BY version DESC LIMIT 1;
 IF FOUND THEN
  NEW.rate_revision := rate.revision;
  NEW.unit_cost_usd := rate.unit_cost_usd;
  NEW.valuation_source := rate.source_reference;
  NEW.estimated := true;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ih_cost_event_rate_pin ON ih_cost_events;
CREATE TRIGGER ih_cost_event_rate_pin BEFORE INSERT ON ih_cost_events
 FOR EACH ROW EXECUTE FUNCTION ih_pin_provider_cost_rate();

CREATE OR REPLACE FUNCTION ih_guard_cost_valuation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE rate ih_cost_rates;
BEGIN
 IF (OLD.id,OLD.run_id,OLD.provider,OLD.cost_type,OLD.quantity,OLD.unit,OLD.source,OLD.created_at)
   IS DISTINCT FROM (NEW.id,NEW.run_id,NEW.provider,NEW.cost_type,NEW.quantity,NEW.unit,NEW.source,NEW.created_at)
   OR (OLD.operation IS NOT NULL AND OLD.operation IS DISTINCT FROM NEW.operation) THEN
  RAISE EXCEPTION 'Measured cost facts are immutable.' USING ERRCODE='23514';
 END IF;
 IF OLD.unit_cost_usd IS NOT NULL AND
  (OLD.unit_cost_usd,OLD.rate_revision,OLD.valuation_source,OLD.estimated)
   IS DISTINCT FROM (NEW.unit_cost_usd,NEW.rate_revision,NEW.valuation_source,NEW.estimated) THEN
  RAISE EXCEPTION 'Pinned cost valuations are immutable.' USING ERRCODE='23514';
 END IF;
 IF NEW.rate_revision IS NOT NULL THEN
  SELECT * INTO rate FROM ih_cost_rates WHERE revision=NEW.rate_revision;
  IF NOT FOUND OR rate.provider<>lower(NEW.provider) OR rate.operation<>NEW.operation
   OR rate.unit<>NEW.unit OR rate.effective_from>NEW.created_at OR NEW.created_at>=rate.effective_until
   OR NEW.unit_cost_usd IS DISTINCT FROM rate.unit_cost_usd
   OR NEW.valuation_source IS DISTINCT FROM rate.source_reference OR NOT NEW.estimated THEN
   RAISE EXCEPTION 'Rate revision does not match the measured cost event.' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ih_cost_event_valuation_guard ON ih_cost_events;
CREATE TRIGGER ih_cost_event_valuation_guard BEFORE UPDATE ON ih_cost_events
 FOR EACH ROW EXECUTE FUNCTION ih_guard_cost_valuation();
"""

FIELDS = "revision,version,provider,operation,unit,unit_cost_usd,source_reference,source_as_of,effective_from,effective_until,created_at"


def _invalid(message):
    raise ControlError('invalid_cost_rate', message, 422)


def rate_body(body):
    allowed={'provider','operation','unit','unit_cost_usd','source_reference','source_as_of','effective_from','effective_until'}
    if not isinstance(body,dict) or set(body)!=allowed:
        _invalid('Supply the documented rate fields, including its source and validity window.')
    result={}
    for name in ('provider','operation'):
        value=body[name]
        if not isinstance(value,str) or not re.fullmatch(r'[a-z0-9][a-z0-9_.:-]{0,79}',value):
            _invalid(f'{name} must be a lowercase provider/operation identifier of at most 80 characters.')
        result[name]=value
    if body['unit']!='provider_credit':
        _invalid('Only reported provider_credit units have a pricing contract here.')
    result['unit']='provider_credit'
    value=body['unit_cost_usd']
    if not isinstance(value,str) or not re.fullmatch(r'(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,12})?',value):
        _invalid('unit_cost_usd must be a nonnegative decimal string with at most 12 decimal places and less than 1000000.')
    result['unit_cost_usd']=format(Decimal(value).normalize(),'f')
    source=body['source_reference']
    if not isinstance(source,str) or not 1<=len(source.strip())<=512 or any(ord(c)<32 for c in source):
        _invalid('source_reference must be a nonempty single-line reference of at most 512 characters.')
    result['source_reference']=source.strip()
    for name in ('source_as_of','effective_from','effective_until'):
        try:
            value=datetime.fromisoformat(body[name])
            if value.tzinfo is None:
                raise ValueError('timezone missing')
            result[name]=value.astimezone(UTC).isoformat()
        except (ValueError,TypeError,OverflowError):
            _invalid(f'{name} must be an ISO timestamp with timezone.')
    if datetime.fromisoformat(result['effective_until'])<=datetime.fromisoformat(result['effective_from']):
        _invalid('effective_until must follow effective_from; the end is exclusive.')
    if datetime.fromisoformat(result['source_as_of'])>datetime.now(UTC):
        _invalid('source_as_of cannot be in the future.')
    return result


class CostRateStore:
    def __init__(self,control):
        self.control=control

    def create(self,body):
        values=rate_body(body)
        revision=hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                        ('|'.join(values[name] for name in ('provider','operation','unit')),))
            cur.execute('''INSERT INTO ih_cost_rates(revision,provider,operation,unit,unit_cost_usd,
                source_reference,source_as_of,effective_from,effective_until)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(revision) DO NOTHING''',
                (revision,*(values[name] for name in ('provider','operation','unit','unit_cost_usd',
                            'source_reference','source_as_of','effective_from','effective_until'))))
            cur.execute(f'SELECT {FIELDS} FROM ih_cost_rates WHERE revision=%s',(revision,))
            return dict(cur.fetchone())

    def list(self,provider,limit,offset):
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT count(*) AS total FROM ih_cost_rates WHERE (%s::text IS NULL OR provider=%s)',(provider,provider))
            total=cur.fetchone()['total']
            cur.execute(f'''SELECT {FIELDS} FROM ih_cost_rates WHERE (%s::text IS NULL OR provider=%s)
                ORDER BY version DESC LIMIT %s OFFSET %s''',(provider,provider,limit,offset))
            return {'rates':[dict(row) for row in cur.fetchall()],'total':total,'limit':limit,'offset':offset}

    def value_run(self,run_id,revision,*,dry_run,limit):
        if not re.fullmatch(r'[a-f0-9]{64}',str(revision)) or type(dry_run) is not bool or type(limit) is not int or not 1<=limit<=500:
            raise ControlError('invalid_valuation','Specify a rate revision, boolean dry_run and limit between 1 and 500.',422)
        self.control.ensure_schema()
        with self.control._connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT id FROM ih_runs WHERE id=%s',(run_id,))
            if not cur.fetchone():
                raise ControlError('run_not_found','Run not found.',404)
            cur.execute(f'SELECT {FIELDS} FROM ih_cost_rates WHERE revision=%s',(revision,))
            rate=cur.fetchone()
            if not rate:
                raise ControlError('rate_not_found','Rate revision not found.',404)
            query='''SELECT id,quantity FROM ih_cost_events WHERE run_id=%s AND unit_cost_usd IS NULL
                AND lower(provider)=%s AND operation=%s AND unit=%s AND created_at>=%s AND created_at<%s
                ORDER BY created_at,id LIMIT %s'''
            if not dry_run:
                query+=' FOR UPDATE'
            cur.execute(query,(run_id,rate['provider'],rate['operation'],rate['unit'],rate['effective_from'],rate['effective_until'],limit))
            rows=cur.fetchall()
            with localcontext() as context:
                context.prec=64
                amount=sum((row['quantity']*rate['unit_cost_usd'] for row in rows),Decimal(0))
            if not dry_run and rows:
                cur.execute('''UPDATE ih_cost_events SET unit_cost_usd=%s,valuation_source=%s,
                    rate_revision=%s,estimated=true WHERE id=ANY(%s) AND unit_cost_usd IS NULL''',
                    (rate['unit_cost_usd'],rate['source_reference'],revision,[row['id'] for row in rows]))
            return {'run_id':run_id,'rate_revision':revision,'dry_run':dry_run,'eligible_count':len(rows),
                    'valued_count':0 if dry_run else len(rows),'estimated_subtotal_usd':amount,'limit':limit}
