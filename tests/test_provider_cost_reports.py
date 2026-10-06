"""Provider response amounts are evidence, not reconciled invoices or full COGS."""
import json
from decimal import Decimal

import httpx
import pytest
from test_cost_events import costs as _costs

from internet_hands.execution_meter import (
    execution_usage_snapshot,
    record_provider_call,
    record_provider_outcome,
    reset_execution_meter,
    start_execution_meter,
)
from internet_hands.research_brand_providers import ExaToolProvider


@pytest.fixture
def dollar_run():
    yield from _costs.__wrapped__()


async def exa_usage(response_text, *, operation='search', status=200, initial=None):
    def receiver(request):
        return httpx.Response(status, text=response_text, headers={'Content-Type': 'application/json'})

    token = start_execution_meter(initial)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(receiver)) as client:
            provider = ExaToolProvider(api_key='exa-private-test-key', client=client)
            record_provider_call('exa')
            arguments = {'query': 'test query'} if operation == 'search' else {'urls': ['https://example.com']}
            result = await provider.execute(operation, arguments)
            record_provider_outcome('exa', ref='exa:' + operation, status='completed')
        return execution_usage_snapshot(), result
    finally:
        reset_execution_meter(token)


async def test_exact_response_amount_is_captured_before_float_rounding():
    usage, result = await exa_usage('{"results":[],"costDollars":{"total":0.123456789123}}')
    reports = usage.get('provider_cost_reports', [])
    assert len(reports) == 1
    assert reports[0]['amount_usd'] == '0.123456789123'
    assert reports[0]['report_state'] == 'reported'
    assert result['metadata']['cost_dollars'] == 0.123456789123
    assert usage['counters']['exa_cost_microusd'] == 123457


async def test_settlement_preserves_reported_dollars_separately_from_rates(dollar_run):
    control, costs, run_id = dollar_run
    usage, _ = await exa_usage('{"results":[],"costDollars":{"total":0.007000000001}}')
    assert usage['counters']['exa_cost_microusd'] == 7000
    control.settle_tool_call(run_id, status='ok', latency_ms=10, output_bytes=20,
                             actual_credits=1, execution_usage=usage)
    report = costs.for_run(run_id, 100, 0)
    assert 'provider_reported_dollars' in report['coverage']
    assert report['summary']['known_reported_provider_subtotal_usd'] == Decimal('0.007000000001')
    assert report['summary']['known_cost_subtotal_usd'] is None
    assert report['summary']['total_cost_usd'] is None


@pytest.mark.parametrize('total,expected', [('0', '0'), ('0.000000000001', '0.000000000001'),
                                          ('9.876543210123e-3', None), ('1e-3', '0.001'),
                                          ('999999.999999999999', '999999.999999999999')])
async def test_exact_zero_and_decimal_bounds(total, expected):
    usage, _ = await exa_usage('{"results":[],"costDollars":{"total":' + total + '}}')
    report = usage['provider_cost_reports'][0]
    assert report['amount_usd'] == expected
    assert report['report_state'] == ('reported' if expected is not None else 'invalid_reported_total')


@pytest.mark.parametrize('costs,state', [
    ('null', 'not_reported'), ('{}', 'not_reported'), ('{"total":null}', 'not_reported'),
    ('[]', 'invalid_reported_total'), ('"private-url-token"', 'invalid_reported_total'),
    ('{"total":true}', 'invalid_reported_total'), ('{"total":-0.01}', 'invalid_reported_total'),
    ('{"total":"0.01"}', 'invalid_reported_total'), ('{"total":[]}', 'invalid_reported_total'),
    ('{"total":{}}', 'invalid_reported_total'), ('{"total":NaN}', 'invalid_reported_total'),
    ('{"total":Infinity}', 'invalid_reported_total'), ('{"total":1e309}', 'invalid_reported_total'),
    ('{"total":1e100000000000000000000000}', 'invalid_reported_total'),
    ('{"total":1000000}', 'invalid_reported_total'), ('{"total":0.0000000000001}', 'invalid_reported_total'),
    ('{"total":' + '1' + '0' * 500 + '}', 'invalid_reported_total'),
])
async def test_malformed_costs_do_not_invent_zero_or_break_usable_results(costs, state):
    usage, result = await exa_usage('{"results":[],"costDollars":' + costs + '}')
    report = usage['provider_cost_reports'][0]
    assert result['status'] == 'completed'
    json.dumps(result, allow_nan=False)
    assert report['amount_usd'] is None and report['report_state'] == state
    assert 'private-url-token' not in str(report)


async def test_checkpoint_recovery_keeps_identity_and_separates_new_responses(dollar_run):
    from copy import deepcopy

    control, costs, run_id = dollar_run
    initial, _ = await exa_usage('{"results":[],"costDollars":{"total":0.003}}')
    before = deepcopy(initial)
    resumed, _ = await exa_usage('{"results":[],"costDollars":{"total":0.004}}',
                                operation='contents', initial=initial)
    assert initial == before
    assert resumed['provider_cost_reports'][0] == initial['provider_cost_reports'][0]
    assert len({item['id'] for item in resumed['provider_cost_reports']}) == 2
    # Repeated snapshots of the same observation cannot duplicate the expense.
    resumed['provider_cost_reports'].append(dict(initial['provider_cost_reports'][0]))
    control.settle_tool_call(run_id, status='ok', latency_ms=10, output_bytes=20,
                             actual_credits=1, execution_usage=resumed)
    report = costs.for_run(run_id, 100, 0)
    coverage = report['coverage']['provider_reported_dollars']
    assert coverage['report_count'] == coverage['observed_call_count'] == 2
    assert coverage['call_without_report_count'] == 0
    assert report['summary']['known_reported_provider_subtotal_usd'] == Decimal('0.007')


async def test_settlement_rollback_removes_reports_and_preserves_retry_identity(dollar_run):
    control, costs, run_id = dollar_run
    usage, _ = await exa_usage('{"results":[],"costDollars":{"total":0.007}}')
    with control._connect() as conn:
        control.settle_tool_call(run_id, status='ok', latency_ms=10, output_bytes=20,
                                 actual_credits=1, execution_usage=usage, transaction=conn)
        conn.rollback()
    assert costs.for_run(run_id, 100, 0)['provider_dollar_reports'] == []
    control.settle_tool_call(run_id, status='ok', latency_ms=10, output_bytes=20,
                             actual_credits=1, execution_usage=usage)
    stored = costs.for_run(run_id, 100, 0)['provider_dollar_reports']
    assert len(stored) == 1 and stored[0]['id'] == usage['provider_cost_reports'][0]['id']


async def test_conflicting_observation_rolls_back_settlement(dollar_run):
    from internet_hands.control_store import ControlError

    control, costs, run_id = dollar_run
    usage, _ = await exa_usage('{"results":[],"costDollars":{"total":0.007}}')
    conflicting = {**usage['provider_cost_reports'][0], 'amount_usd': '0.999'}
    usage['provider_cost_reports'].append(conflicting)
    with pytest.raises(ControlError) as denied:
        control.settle_tool_call(run_id, status='ok', latency_ms=10, output_bytes=20,
                                 actual_credits=1, execution_usage=usage)
    assert denied.value.code == 'provider_cost_report_conflict'
    assert costs.for_run(run_id, 100, 0)['provider_dollar_reports'] == []
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT status,credits_charged FROM ih_usage_events WHERE request_id=%s', (run_id,))
        assert cur.fetchone() == {'status': 'reserved', 'credits_charged': 0}


async def test_concurrent_and_late_settlement_never_duplicate_or_rewrite(dollar_run):
    from concurrent.futures import ThreadPoolExecutor

    control, costs, run_id = dollar_run
    usage, _ = await exa_usage('{"results":[],"costDollars":{"total":0.007}}')

    def settle():
        return control.settle_tool_call(run_id, status='ok', latency_ms=10, output_bytes=20,
                                        actual_credits=1, execution_usage=usage)

    with ThreadPoolExecutor(max_workers=2) as workers:
        charges = list(workers.map(lambda _: settle(), range(2)))
    assert charges[0] == charges[1]
    later, _ = await exa_usage('{"results":[],"costDollars":{"total":0.999}}')
    control.settle_tool_call(run_id, status='error', latency_ms=100, output_bytes=0,
                             actual_credits=0, execution_usage=later)
    report = costs.for_run(run_id, 100, 0)
    assert len(report['provider_dollar_reports']) == 1
    assert report['summary']['known_reported_provider_subtotal_usd'] == Decimal('0.007')


async def test_real_mesh_retry_leaves_non_success_response_cost_unknown(dollar_run, monkeypatch):
    from internet_hands.provider_reliability import provider_reliability
    from internet_hands.tool_mesh import ToolMesh

    monkeypatch.setenv('OPENCRAWL_PROVIDER_READ_RETRIES', '1')
    monkeypatch.setenv('OPENCRAWL_PROVIDER_RETRY_BASE_MS', '1')
    provider_reliability.reset('exa')
    control, costs, run_id = dollar_run
    responses = iter([(503, '{"costDollars":{"total":1}}'),
                      (200, '{"results":[],"costDollars":{"total":0.007}}')])

    def receiver(request):
        status, body = next(responses)
        return httpx.Response(status, text=body, headers={'Content-Type': 'application/json'})

    token = start_execution_meter()
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(receiver)) as client:
            mesh = ToolMesh([ExaToolProvider(api_key='exa-test-key', client=client)])
            result = await mesh.execute('exa:search', {'query': 'test query'})
        usage = execution_usage_snapshot()
    finally:
        reset_execution_meter(token)
        provider_reliability.reset('exa')
    assert result['status'] == 'completed'
    assert usage['provider_calls']['exa'] == 2 and len(usage['provider_cost_reports']) == 1
    control.settle_tool_call(run_id, status='ok', latency_ms=10, output_bytes=20,
                             actual_credits=1, execution_usage=usage)
    coverage = costs.for_run(run_id, 100, 0)['coverage']['provider_reported_dollars']
    assert coverage['observed_call_count'] == 2 and coverage['call_without_report_count'] == 1
    assert coverage['known_reported_subtotal_usd'] == Decimal('0.007')
    assert coverage['reconciliation_state'] == 'unreconciled'


async def test_all_events_summary_is_independent_of_report_pagination(dollar_run):
    control, costs, run_id = dollar_run
    usage = None
    for value in ('0.001', '0', 'null'):
        usage, _ = await exa_usage('{"results":[],"costDollars":{"total":' + value + '}}', initial=usage)
    control.settle_tool_call(run_id, status='ok', latency_ms=10, output_bytes=20,
                             actual_credits=1, execution_usage=usage)
    first = costs.for_run(run_id, 1, 0)
    second = costs.for_run(run_id, 1, 1)
    empty = costs.for_run(run_id, 1, 3)
    assert len(first['provider_dollar_reports']) == len(second['provider_dollar_reports']) == 1
    assert first['provider_dollar_reports'][0]['id'] != second['provider_dollar_reports'][0]['id']
    assert empty['provider_dollar_reports'] == []
    assert first['summary'] == second['summary'] == empty['summary']
    coverage = first['coverage']['provider_reported_dollars']
    assert coverage['report_count'] == 3 and coverage['reported_amount_count'] == 2
    assert coverage['not_reported_count'] == 1 and coverage['known_reported_subtotal_usd'] == Decimal('0.001')


async def test_schema_reinstall_does_not_reconstruct_rounded_legacy_costs(dollar_run):
    from internet_hands.control_store import ControlStore
    from internet_hands.cost_events import CostEventStore

    control, costs, run_id = dollar_run
    control.settle_tool_call(run_id, status='ok', latency_ms=10, output_bytes=20,
                             actual_credits=1, execution_usage={'counters': {'exa_cost_microusd': 7000},
                                                               'provider_calls': {'exa': 1}})
    before = costs.for_run(run_id, 100, 0)
    other = ControlStore(control.dsn)
    other.ensure_schema()
    assert CostEventStore(other).for_run(run_id, 100, 0) == before
    coverage = before['coverage']['provider_reported_dollars']
    assert coverage['report_count'] == 0 and coverage['call_without_report_count'] == 1
    assert before['summary']['known_reported_provider_subtotal_usd'] is None


async def test_reports_survive_output_deletion_and_follow_account_lifecycle(dollar_run):
    from internet_hands.datasets import DatasetStore

    control, costs, run_id = dollar_run
    usage, _ = await exa_usage('{"results":[],"costDollars":{"total":0.007}}')
    control.settle_tool_call(run_id, status='ok', latency_ms=10, output_bytes=20,
                             actual_credits=1, execution_usage=usage)
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT user_id FROM ih_usage_events WHERE request_id=%s', (run_id,))
        owner = cur.fetchone()['user_id']
    datasets = DatasetStore(control)
    dataset = datasets.save(owner, run_id, 'search', {'search_results': []}, 'Search')
    before = costs.for_run(run_id, 100, 0)['provider_dollar_reports']
    datasets.delete(owner, dataset['id'])
    assert costs.for_run(run_id, 100, 0)['provider_dollar_reports'] == before
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('DELETE FROM ih_users WHERE id=%s', (owner,))
        cur.execute('SELECT count(*) AS count FROM ih_provider_dollar_reports WHERE run_id=%s', (run_id,))
        assert cur.fetchone()['count'] == 0


async def test_operator_reads_exact_amounts_and_customer_metadata_has_no_reports(dollar_run, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from internet_hands import cost_events_api
    from internet_hands.run_envelope import RunEnvelopeStore
    from internet_hands.usage_intelligence import UsageIntelligence

    control, costs, run_id = dollar_run
    usage, _ = await exa_usage('{"results":[],"costDollars":{"total":0.007000000001}}')
    control.settle_tool_call(run_id, status='ok', latency_ms=10, output_bytes=20,
                             actual_credits=1, execution_usage=usage)
    monkeypatch.setattr(cost_events_api, 'costs', costs)
    monkeypatch.setenv('CRON_SECRET', 'isolated-operator-secret')
    app = FastAPI()
    app.include_router(cost_events_api.router)
    client = TestClient(app)
    path = '/api/internal/runs/' + run_id + '/economics'
    assert client.get(path).status_code == 401
    assert client.get(path, headers={'Authorization': 'Bearer customer-key'}).status_code == 401
    response = client.get(path, headers={'Authorization': 'Bearer isolated-operator-secret'})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert response.json()['provider_dollar_reports'][0]['amount_usd'] == '0.007000000001'
    assert 'exa-private-test-key' not in response.text and 'test query' not in response.text
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT user_id FROM ih_usage_events WHERE request_id=%s', (run_id,))
        owner = cur.fetchone()['user_id']
    public = [RunEnvelopeStore(control).get(owner, run_id, 0, 100),
              UsageIntelligence(control).run_detail(owner, run_id), control.wallet_ledger(owner)]
    for private in ('provider_cost_reports', 'amount_usd', usage['provider_cost_reports'][0]['id']):
        assert private not in str(public)
    assert len(control.wallet_ledger(owner)['ledger']) == 1


async def test_new_rate_revisions_cannot_reprice_or_double_count_dollar_reports(dollar_run):
    from datetime import UTC, datetime, timedelta

    from psycopg.errors import CheckViolation

    from internet_hands.cost_rates import CostRateStore

    control, costs, run_id = dollar_run
    now = datetime.now(UTC)
    rates = CostRateStore(control)
    body = {'provider': 'exa', 'operation': 'search', 'unit': 'provider_credit', 'unit_cost_usd': '0.009',
            'source_reference': 'overlap-test-contract', 'source_as_of': now.isoformat(),
            'effective_from': (now - timedelta(days=1)).isoformat(), 'effective_until': (now + timedelta(days=1)).isoformat()}
    rates.create(body)
    usage, _ = await exa_usage('{"results":[],"costDollars":{"total":0.007}}')
    usage['provider_usage'] = [{'provider': 'exa', 'operation': 'search', 'credits_used': 1}]
    control.settle_tool_call(run_id, status='ok', latency_ms=10, output_bytes=20,
                             actual_credits=1, execution_usage=usage)
    before = costs.for_run(run_id, 100, 0)
    assert before['summary']['known_cost_subtotal_usd'] == Decimal('0.009')
    assert before['summary']['known_reported_provider_subtotal_usd'] == Decimal('0.007')
    assert before['summary']['total_cost_usd'] is None
    assert before['coverage']['provider_reported_dollars']['overlapping_credit_operation_count'] == 1
    rates.create({**body, 'unit_cost_usd': '0.999'})
    assert costs.for_run(run_id, 100, 0)['provider_dollar_reports'] == before['provider_dollar_reports']
    with control._connect() as conn, conn.cursor() as cur:
        for assignment in ("amount_usd=0.999", "report_state='not_reported',amount_usd=NULL", "operation='contents'"):
            with pytest.raises(CheckViolation, match='immutable'), conn.transaction():
                cur.execute(f'UPDATE ih_provider_dollar_reports SET {assignment} WHERE run_id=%s', (run_id,))


async def test_charge_validation_failure_rolls_back_new_cost_evidence(dollar_run):
    from internet_hands.control_store import ControlError

    control, costs, run_id = dollar_run
    usage, _ = await exa_usage('{"results":[],"costDollars":{"total":0.007}}')
    raw_reserved = control.raw_tool_reservation(run_id)
    with pytest.raises(ControlError) as denied:
        control.settle_tool_call(run_id, status='ok', latency_ms=10, output_bytes=20,
                                 actual_credits=raw_reserved + 1, execution_usage=usage)
    assert denied.value.code == 'reservation_exceeded'
    assert costs.for_run(run_id, 100, 0)['provider_dollar_reports'] == []


async def test_failed_run_retains_observed_provider_cost_even_without_wallet_charge(dollar_run):
    control, costs, run_id = dollar_run
    usage, _ = await exa_usage('{"results":[],"costDollars":{"total":0.007}}')
    charge = control.settle_tool_call(run_id, status='error', latency_ms=10, output_bytes=0,
                                      actual_credits=0, execution_usage=usage)
    assert charge == 0
    report = costs.for_run(run_id, 100, 0)
    assert report['summary']['known_reported_provider_subtotal_usd'] == Decimal('0.007')
    assert report['summary']['cost_state'] == 'unknown' and report['summary']['total_cost_usd'] is None


async def test_unknown_and_zero_reports_are_persisted_without_fabricated_prices(dollar_run):
    control, costs, run_id = dollar_run
    usage = None
    for body in ('{}', '{"costDollars":{"total":true}}', '{"costDollars":{"total":0}}'):
        usage, _ = await exa_usage(body, initial=usage)
    control.settle_tool_call(run_id, status='ok', latency_ms=10, output_bytes=20,
                             actual_credits=1, execution_usage=usage)
    coverage = costs.for_run(run_id, 100, 0)['coverage']['provider_reported_dollars']
    assert coverage['report_count'] == 3 and coverage['reported_amount_count'] == 1
    assert coverage['not_reported_count'] == coverage['invalid_report_count'] == 1
    assert coverage['known_reported_subtotal_usd'] == 0
    assert coverage['reconciliation_state'] == 'unreconciled'


async def test_malformed_checkpoint_envelopes_remain_unknown_without_storing_raw_values(dollar_run):
    control, costs, run_id = dollar_run
    usage, _ = await exa_usage('{"results":[],"costDollars":{"total":0.007}}')
    original = usage['provider_cost_reports'][0]
    usage['provider_cost_reports'] = [
        {**original, 'amount_usd': 'private-secret-value', 'body': 'private-response'},
        {**original, 'source': 'https://private.example/token'},
        {**original, 'observed_at': 'invalid-date'},
        {**original, 'id': 'invalid-id'}, 'private-extra',
    ]
    control.settle_tool_call(run_id, status='ok', latency_ms=10, output_bytes=20,
                             actual_credits=1, execution_usage=usage)
    report = costs.for_run(run_id, 100, 0)
    coverage = report['coverage']['provider_reported_dollars']
    assert coverage['report_count'] == coverage['invalid_report_count'] == 1
    assert report['provider_dollar_reports'][0]['amount_usd'] is None
    assert 'private-' not in str(report) and 'private.example' not in str(report)


async def test_concurrent_provider_calls_have_distinct_observations_without_context_leaks():
    import asyncio

    def receiver(request):
        value = '0.003' if request.url.path == '/search' else '0.004'
        return httpx.Response(200, text='{"costDollars":{"total":' + value + '}}')

    token = start_execution_meter()
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(receiver)) as client:
            provider = ExaToolProvider(api_key='exa-test-key', client=client)
            await asyncio.gather(provider.execute('search', {'query': 'test query'}),
                                 provider.execute('contents', {'urls': ['https://example.com']}))
        reports = execution_usage_snapshot()['provider_cost_reports']
    finally:
        reset_execution_meter(token)
    assert len({item['id'] for item in reports}) == 2
    assert {item['operation']: item['amount_usd'] for item in reports} == {'search': '0.003', 'contents': '0.004'}
    assert 'provider_cost_reports' not in execution_usage_snapshot()
