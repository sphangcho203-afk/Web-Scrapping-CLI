"""Exact response-level dollar observations; invoice reconciliation is separate."""
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext

SOURCE = 'exa_response_cost_dollars_total'
OPERATIONS = ('search', 'contents')
STATES = ('reported', 'not_reported', 'invalid_reported_total')

SCHEMA = """
CREATE TABLE IF NOT EXISTS ih_provider_dollar_reports (
 run_id text NOT NULL REFERENCES ih_runs(id) ON DELETE CASCADE,
 id text NOT NULL CHECK(id ~ '^pcost_[a-f0-9]{32}$'),
 provider text NOT NULL CHECK(provider='exa'),
 operation text NOT NULL CHECK(operation IN ('search','contents')),
 source text NOT NULL CHECK(source='exa_response_cost_dollars_total'),
 report_state text NOT NULL CHECK(report_state IN ('reported','not_reported','invalid_reported_total')),
 amount_usd numeric CHECK(amount_usd>=0 AND amount_usd<1000000 AND scale(amount_usd)<=12),
 observed_at timestamptz NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(run_id,id),
 CHECK((report_state='reported' AND amount_usd IS NOT NULL)
    OR (report_state<>'reported' AND amount_usd IS NULL))
);
CREATE INDEX IF NOT EXISTS ih_provider_dollar_report_page_idx ON ih_provider_dollar_reports(run_id,observed_at,id);
CREATE OR REPLACE FUNCTION ih_guard_provider_dollar_report() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Provider dollar reports are immutable.' USING ERRCODE='23514';
END $$;
DROP TRIGGER IF EXISTS ih_provider_dollar_report_guard ON ih_provider_dollar_reports;
CREATE TRIGGER ih_provider_dollar_report_guard BEFORE UPDATE ON ih_provider_dollar_reports
 FOR EACH ROW EXECUTE FUNCTION ih_guard_provider_dollar_report();
"""


def response_decimal(token):
    try:
        return Decimal(token)
    except InvalidOperation:
        return Decimal('NaN')  # Unrepresentable numeric tokens are invalid evidence.


def exact_dollars(value):
    """Accept JSON integers/decimals without coercing malformed values to zero."""
    if type(value) is not int and not isinstance(value, Decimal):
        return None
    value = Decimal(value)
    if not value.is_finite() or not 0 <= value < 1_000_000:
        return None
    with localcontext() as context:
        context.prec = 30
        if value != value.quantize(Decimal('0.000000000001')):
            return None
        return format(value.normalize(), 'f') if value else '0'


def exa_report(operation, costs):
    """Called from the decimal JSON decoder while the response is in hand."""
    if operation not in OPERATIONS:
        raise ValueError('Unsupported Exa cost operation')
    total = costs.get('total') if isinstance(costs, dict) else None
    amount = exact_dollars(total)
    state = ('reported' if amount is not None else 'not_reported'
             if costs is None or isinstance(costs, dict) and total is None else 'invalid_reported_total')
    return {'id': 'pcost_' + uuid.uuid4().hex, 'provider': 'exa', 'operation': operation,
            'source': SOURCE, 'report_state': state, 'amount_usd': amount,
            'observed_at': datetime.now(UTC).isoformat()}


def normalize_reports(reports):
    """Check persisted checkpoint identities and retain only the private contract."""
    if not isinstance(reports, list):
        return []
    result = []
    for item in reports:
        if not isinstance(item, dict) or item.get('provider') != 'exa' or item.get('source') != SOURCE:
            continue
        if item.get('operation') not in OPERATIONS or item.get('report_state') not in STATES:
            continue
        if not isinstance(item.get('id'), str) or not re.fullmatch(r'pcost_[a-f0-9]{32}', item['id']):
            continue
        observed = item.get('observed_at')
        if not isinstance(observed, str) or len(observed) > 64:
            continue
        try:
            observed = datetime.fromisoformat(observed)
            if observed.tzinfo is None:
                continue
            observed = observed.astimezone(UTC).isoformat()
        except (ValueError, OverflowError):
            continue
        amount = None
        state = item['report_state']
        if state == 'reported':
            raw = item.get('amount_usd')
            try:
                if isinstance(raw, str) and re.fullmatch(r'[0-9]{1,6}(?:\.[0-9]{1,12})?', raw):
                    amount = exact_dollars(Decimal(raw))
            except InvalidOperation:
                pass
            if amount is None:
                state = 'invalid_reported_total'
        result.append({'id': item['id'], 'provider': 'exa', 'operation': item['operation'],
                       'source': SOURCE, 'report_state': state, 'amount_usd': amount,
                       'observed_at': observed})
    return result


def persist_reports(cur, run_id, reports):
    """Inside settlement, identical checkpoint replay is safe; conflicting IDs fail."""
    from .control_store import ControlError

    for item in normalize_reports(reports):
        values = (run_id, item['id'], item['operation'], item['source'], item['report_state'],
                  item['amount_usd'], item['observed_at'])
        cur.execute('''INSERT INTO ih_provider_dollar_reports
            (run_id,id,provider,operation,source,report_state,amount_usd,observed_at)
            VALUES(%s,%s,'exa',%s,%s,%s,%s::numeric,%s::timestamptz) ON CONFLICT DO NOTHING''', values)
        if not cur.rowcount:
            cur.execute('''SELECT id FROM ih_provider_dollar_reports WHERE run_id=%s AND id=%s
                AND operation=%s AND source=%s AND report_state=%s
                AND amount_usd IS NOT DISTINCT FROM %s::numeric AND observed_at=%s::timestamptz''', values)
            if not cur.fetchone():
                raise ControlError('provider_cost_report_conflict',
                                   'Provider cost observation identity has conflicting evidence.', 409)


def read_reports(cur, run_id, expected_calls, limit, offset):
    cur.execute('''SELECT count(*) AS report_count,
        count(*) FILTER(WHERE report_state='reported') AS reported_amount_count,
        count(*) FILTER(WHERE report_state='not_reported') AS not_reported_count,
        count(*) FILTER(WHERE report_state='invalid_reported_total') AS invalid_report_count,
        sum(amount_usd) AS known_reported_subtotal_usd FROM ih_provider_dollar_reports WHERE run_id=%s''', (run_id,))
    coverage = dict(cur.fetchone())
    cur.execute('''SELECT count(*) AS count FROM ih_provider_usage
        WHERE request_id=%s AND lower(provider)='exa' AND measurement_kind='attempt' ''', (run_id,))
    observed_calls = max(expected_calls, cur.fetchone()['count'], coverage['report_count'])
    coverage['observed_call_count'] = observed_calls
    coverage['call_without_report_count'] = observed_calls - coverage['report_count']
    cur.execute('''SELECT count(DISTINCT operation) AS count FROM ih_provider_usage p
        WHERE request_id=%s AND lower(provider)='exa' AND measurement_kind='attempt'
        AND NOT EXISTS(SELECT 1 FROM ih_provider_dollar_reports d
            WHERE d.run_id=p.request_id AND d.operation=p.operation)''', (run_id,))
    coverage['operation_without_report_count'] = cur.fetchone()['count']
    cur.execute('''SELECT count(DISTINCT operation) AS count FROM ih_cost_events c
        WHERE run_id=%s AND lower(provider)='exa' AND EXISTS (
            SELECT 1 FROM ih_provider_dollar_reports d WHERE d.run_id=c.run_id AND d.operation=c.operation)''', (run_id,))
    coverage['overlapping_credit_operation_count'] = cur.fetchone()['count']
    coverage.update(state='partial', providers=['exa'], reconciliation_state='unreconciled',
                    historical_coverage='not_reconstructed')
    cur.execute('''SELECT id,provider,operation,source,report_state,amount_usd,observed_at,recorded_at
        FROM ih_provider_dollar_reports WHERE run_id=%s ORDER BY observed_at,id LIMIT %s OFFSET %s''',
                (run_id, limit, offset))
    return coverage, [dict(row) for row in cur.fetchall()]
