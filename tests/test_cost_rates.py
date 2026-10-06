import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from internet_hands.control_store import AuthIdentity, ControlError, ControlStore
from internet_hands.cost_events import CostEventStore
from internet_hands.cost_rates import CostRateStore


@pytest.fixture
def economics():
    dsn=os.getenv('OPENCRAWL_TEST_DATASET_DSN')
    if not dsn:
        pytest.skip('Requires isolated PostgreSQL')
    control=ControlStore(dsn)
    control.ensure_schema()
    owner='rates_'+uuid.uuid4().hex
    provider='provider-'+uuid.uuid4().hex
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('INSERT INTO ih_users(id,email) VALUES (%s,%s)',(owner,owner+'@test.invalid'))
        cur.execute('INSERT INTO ih_wallets(user_id,monthly_credits) VALUES (%s,100000)',(owner,))
    identity=AuthIdentity(owner,None,['*'],'free',100,'session',10)
    now=datetime.now(UTC)
    body={'provider':provider,'operation':'extract','unit':'provider_credit',
          'unit_cost_usd':'0.001234567891','source_reference':'invoice-fixture',
          'source_as_of':now.isoformat(),'effective_from':(now-timedelta(days=1)).isoformat(),
          'effective_until':(now+timedelta(days=1)).isoformat()}
    def settle(units=3, operation='extract', extra=None):
        run='req_'+uuid.uuid4().hex
        control.reserve_tool_call(identity=identity,request_id=run,tool_name='playground:search',arguments=None,input_bytes=0)
        usage={'provider_usage':[{'provider':provider,'operation':operation,'credits_used':units}],**(extra or {})}
        control.settle_tool_call(run,status='ok',latency_ms=10,output_bytes=20,actual_credits=1,execution_usage=usage)
        return run
    try:
        yield control,CostRateStore(control),CostEventStore(control),body,settle
    finally:
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute('DELETE FROM ih_users WHERE id=%s',(owner,))


def test_rate_revision_is_idempotent_immutable_and_values_only_matching_units(economics):
    control,rates,costs,body,settle=economics
    with ThreadPoolExecutor(max_workers=4) as pool:
        revisions=list(pool.map(lambda _:rates.create(body),range(4)))
    first=revisions[0]
    assert len({rate['revision'] for rate in revisions})==1
    run=settle()
    report=costs.for_run(run,100,0)
    assert report['events'][0]['rate_revision']==first['revision']
    assert report['events'][0]['total_cost_usd']==Decimal('0.003703703673')
    assert report['events'][0]['estimated'] is True
    assert report['summary']['cost_state']=='unknown'
    second=rates.create({**body,'unit_cost_usd':'0.009','source_reference':'revised-invoice-fixture'})
    assert second['version']>first['version']
    assert costs.for_run(run,100,0)['events'][0]['rate_revision']==first['revision']
    assert costs.for_run(settle(),100,0)['events'][0]['rate_revision']==second['revision']
    assert costs.for_run(settle(operation='search'),100,0)['events'][0]['unit_cost_usd'] is None
    with control._connect() as conn, conn.cursor() as cur:
        from psycopg.errors import CheckViolation
        with pytest.raises(CheckViolation,match='immutable'):
            cur.execute('UPDATE ih_cost_rates SET unit_cost_usd=1 WHERE revision=%s',(first['revision'],))
        conn.rollback()


def test_review_historical_valuation_pins_a_revision_and_does_not_reprice(economics):
    _,rates,costs,body,settle=economics
    run=settle(units=7)
    rate=rates.create(body)
    assert costs.for_run(run,100,0)['events'][0]['unit_cost_usd'] is None
    review=rates.value_run(run,rate['revision'],dry_run=True,limit=100)
    assert review['eligible_count']==1 and review['estimated_subtotal_usd']==Decimal('0.008641975237')
    assert costs.for_run(run,100,0)['events'][0]['unit_cost_usd'] is None
    applied=rates.value_run(run,rate['revision'],dry_run=False,limit=100)
    assert applied['valued_count']==1
    assert rates.value_run(run,rate['revision'],dry_run=False,limit=100)['valued_count']==0
    replacement=rates.create({**body,'unit_cost_usd':'1'})
    assert rates.value_run(run,replacement['revision'],dry_run=False,limit=100)['valued_count']==0
    assert costs.for_run(run,100,0)['events'][0]['rate_revision']==rate['revision']


def test_expired_future_and_unknown_quantities_do_not_become_known_costs(economics):
    _,rates,costs,body,settle=economics
    now=datetime.now(UTC)
    rates.create({**body,'effective_from':(now-timedelta(days=2)).isoformat(),
        'effective_until':(now-timedelta(days=1)).isoformat()})
    rates.create({**body,'effective_from':(now+timedelta(days=1)).isoformat(),
        'effective_until':(now+timedelta(days=2)).isoformat()})
    assert costs.for_run(settle(),100,0)['events'][0]['unit_cost_usd'] is None
    report=costs.for_run(settle(units=None),100,0)
    assert report['summary']['provider_unit_valuation_state']=='unknown'
    assert report['coverage']['provider_units']['missing_quantity_count']==1
    assert report['summary']['provider_cost_total_usd'] is None
    assert report['coverage']['compute']['state']=='not_instrumented'


@pytest.mark.parametrize('changes',[
    {'unit_cost_usd':0.1},{'unit_cost_usd':'NaN'},{'unit_cost_usd':'-1'},
    {'unit_cost_usd':'0.0000000000001'},{'source_reference':''},
    {'effective_until':'2000-01-01T00:00:00Z'},{'source_as_of':'2000-01-01'},
    {'unit':'browser_minute'},{'extra':'unsupported'},
])
def test_invalid_rates_are_rejected(changes,economics):
    _,rates,_,body,_=economics
    with pytest.raises(ControlError) as error:
        rates.create({**body,**changes})
    assert error.value.status_code==422


def test_operator_rates_api_keeps_precision_and_rejects_customer_keys(economics,monkeypatch):
    from internet_hands import cost_events_api
    control,rates,costs,body,settle=economics
    monkeypatch.setattr(cost_events_api,'rates',rates)
    monkeypatch.setattr(cost_events_api,'costs',costs)
    monkeypatch.setenv('CRON_SECRET','operator-secret')
    app=FastAPI();app.include_router(cost_events_api.router)
    client=TestClient(app)
    path='/api/internal/cost-rates'
    assert client.post(path,json=body).status_code==401
    assert client.post(path,headers={'Authorization':'Bearer customer-key'},json=body).status_code==401
    headers={'Authorization':'Bearer operator-secret'}
    response=client.post(path,headers=headers,json=body)
    assert response.status_code==201
    assert response.json()['rate']['unit_cost_usd']=='0.001234567891'
    assert response.headers['Cache-Control']=='no-store'
    assert client.get(path,headers=headers).status_code==200
    run=settle()
    report=client.get('/api/internal/runs/'+run+'/economics',headers=headers).json()
    assert report['events'][0]['total_cost_usd']=='0.003703703673'
    from internet_hands.run_envelope import RunEnvelopeStore
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT user_id FROM ih_usage_events WHERE request_id=%s',(run,))
        owner=cur.fetchone()['user_id']
    public=RunEnvelopeStore(control).get(owner,run,0,100)
    assert 'unit_cost_usd' not in str(public) and 'rate_revision' not in str(public)


def test_missing_measurements_block_provider_total_even_when_other_events_are_priced(economics):
    control,rates,costs,body,settle=economics
    rates.create(body)
    run=settle(extra={'provider_calls':{'another-provider':1},
                     'counters':{'intelligence_browser_elapsed_ms':3750}})
    report=costs.for_run(run,100,0)
    assert report['summary']['known_cost_subtotal_usd']==Decimal('0.003703703673')
    assert report['summary']['provider_cost_total_usd'] is None
    assert report['coverage']['provider_units']['missing_provider_count']==1
    browser=report['coverage']['browser']
    assert browser['state']=='partial' and browser['valuation_state']=='unknown'
    assert browser['measurements'][0]['quantity']==3750
    assert report['summary']['total_cost_usd'] is None
    # Reinstalling the additive schema does not reprice pinned rows or duplicate measurements.
    other=ControlStore(control.dsn);other.ensure_schema()
    after=CostEventStore(other).for_run(run,100,0)
    assert after==report


def test_concurrent_reviewed_valuation_only_prices_the_event_once(economics):
    _,rates,costs,body,settle=economics
    run=settle()
    rate=rates.create(body)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:rates.value_run(run,rate['revision'],dry_run=False,limit=100),range(4)))
    assert sum(result['valued_count'] for result in results)==1
    assert costs.for_run(run,100,0)['events'][0]['total_cost_usd']==Decimal('0.003703703673')


def test_pinned_cost_facts_cannot_be_rewritten_or_receive_an_unrelated_rate(economics):
    from psycopg.errors import CheckViolation
    control,rates,costs,body,settle=economics
    rate=rates.create(body)
    run=settle()
    event=costs.for_run(run,100,0)['events'][0]
    with control._connect() as conn, conn.cursor() as cur:
        with pytest.raises(CheckViolation,match='immutable'):
            cur.execute('UPDATE ih_cost_events SET unit_cost_usd=1 WHERE id=%s',(event['id'],))
        conn.rollback()
        with pytest.raises(CheckViolation,match='immutable'):
            cur.execute('UPDATE ih_cost_events SET quantity=999 WHERE id=%s',(event['id'],))
        conn.rollback()
    unknown=costs.for_run(settle(operation='search'),100,0)['events'][0]
    with control._connect() as conn, conn.cursor() as cur:
        with pytest.raises(CheckViolation,match='does not match'):
            cur.execute('UPDATE ih_cost_events SET unit_cost_usd=%s,rate_revision=%s,valuation_source=%s,estimated=true WHERE id=%s',
                (rate['unit_cost_usd'],rate['revision'],rate['source_reference'],unknown['id']))
        conn.rollback()



def test_stale_and_unreviewed_rates_have_actionable_reasons(economics):
    _,rates,costs,body,settle=economics
    run=settle()
    assert costs.for_run(run,100,0)['summary']['unpriced_reason_counts']=={'missing_rate':1}
    rate=rates.create(body)
    assert costs.for_run(run,100,0)['summary']['unpriced_reason_counts']=={'valuation_required':1}
    rates.value_run(run,rate['revision'],dry_run=False,limit=100)
    assert costs.for_run(run,100,0)['summary']['unpriced_reason_counts']=={}
    now=datetime.now(UTC)
    rate=rates.create({**body,'operation':'search','effective_from':(now-timedelta(days=2)).isoformat(),
        'effective_until':(now-timedelta(days=1)).isoformat()})
    assert costs.for_run(settle(operation='search'),100,0)['summary']['unpriced_reason_counts']=={'outside_validity_window':1}


@pytest.mark.parametrize('quantity',[-1,1.5,True,float('nan'),float('inf'),2_147_483_648])
def test_invalid_reported_units_cannot_be_priced_as_zero_or_truncated(economics,quantity):
    _,rates,costs,body,settle=economics
    rates.create(body)
    report=costs.for_run(settle(units=quantity),100,0)
    assert report['events']==[]
    assert report['coverage']['provider_units']['missing_quantity_count']==1
    assert report['summary']['provider_cost_total_usd'] is None


def test_operator_valuation_requires_explicit_commit_and_enforces_body_bounds(economics,monkeypatch):
    from internet_hands import cost_events_api
    _,rates,costs,body,settle=economics
    monkeypatch.setattr(cost_events_api,'rates',rates)
    monkeypatch.setattr(cost_events_api,'costs',costs)
    monkeypatch.setenv('CRON_SECRET','operator-secret')
    app=FastAPI();app.include_router(cost_events_api.router)
    client=TestClient(app)
    run=settle()
    revision=rates.create(body)['revision']
    path=f'/api/internal/runs/{run}/economics/value'
    headers={'Authorization':'Bearer operator-secret'}
    assert client.post(path,headers={'Authorization':'Bearer customer-key'},content='bad-json').status_code==401
    preview=client.post(path,headers=headers,json={'rate_revision':revision})
    assert preview.status_code==200 and preview.json()['dry_run'] is True
    assert preview.json()['estimated_subtotal_usd']=='0.003703703673'
    assert costs.for_run(run,100,0)['events'][0]['rate_revision'] is None
    for options in ({'dry_run':'false'},{'limit':501},{'limit':True},{'replace_existing':True}):
        assert client.post(path,headers=headers,json={'rate_revision':revision,**options}).status_code==422
    assert client.post(path,headers=headers,content='bad-json').status_code==400
    assert client.post(path,headers=headers,content=' '*8193).status_code==413
    commit=client.post(path,headers=headers,json={'rate_revision':revision,'dry_run':False})
    assert commit.status_code==200 and commit.json()['valued_count']==1
    assert client.post(path,headers=headers,json={'rate_revision':revision,'dry_run':False}).json()['valued_count']==0


def test_validity_start_is_inclusive_and_end_exclusive(economics):
    control,rates,costs,body,settle=economics
    rate=rates.create(body)
    run=settle(units=None)
    with control._connect() as conn, conn.cursor() as cur:
        for timestamp in (rate['effective_from'],rate['effective_until']):
            cur.execute('''INSERT INTO ih_provider_usage(id,request_id,provider,operation,credits_used,status,measurement_kind,created_at)
                VALUES (%s,%s,%s,'extract',1,'ok','usage',%s)''',
                ('pru_'+uuid.uuid4().hex,run,body['provider'],timestamp))
    events=costs.for_run(run,100,0)['events']
    assert events[0]['rate_revision']==rate['revision']
    assert events[1]['rate_revision'] is None


def test_unmeasured_operation_of_a_priced_provider_blocks_provider_total(economics):
    _,rates,costs,body,settle=economics
    rates.create(body)
    run=settle(extra={'provider_events':[{'provider':body['provider'],'ref':body['provider']+':search','status':'ok'}]})
    report=costs.for_run(run,100,0)
    assert report['coverage']['provider_units']['missing_operation_count']==1
    assert report['summary']['provider_cost_total_usd'] is None
    assert report['summary']['known_cost_subtotal_usd']==Decimal('0.003703703673')
