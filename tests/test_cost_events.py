import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from internet_hands.control_store import AuthIdentity, ControlError, ControlStore
from internet_hands.cost_events import CostEventStore


@pytest.fixture
def costs():
    dsn = os.getenv('OPENCRAWL_TEST_DATASET_DSN')
    if not dsn:
        pytest.skip('Requires isolated PostgreSQL')
    control=ControlStore(dsn)
    control.ensure_schema()
    owner='cost_'+uuid.uuid4().hex
    request_id='req_'+uuid.uuid4().hex
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('INSERT INTO ih_users(id,email) VALUES (%s,%s)',(owner,owner+'@test.invalid'))
        cur.execute('INSERT INTO ih_wallets(user_id,monthly_credits) VALUES (%s,100000)',(owner,))
    identity=AuthIdentity(owner,None,['*'],'free',100,'session',10)
    control.reserve_tool_call(identity=identity,request_id=request_id,tool_name='playground:search',arguments=None,input_bytes=0)
    try:
        yield control,CostEventStore(control),request_id
    finally:
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute('DELETE FROM ih_users WHERE id=%s',(owner,))


def test_reported_units_persist_atomically_without_fabricated_dollars(costs):
    control,events,run_id=costs
    measured={'provider_usage':[{'provider':'test-provider','operation':'extract','credits_used':3}]}
    control.settle_tool_call(run_id,status='ok',latency_ms=10,output_bytes=30,actual_credits=1,execution_usage=measured)
    control.settle_tool_call(run_id,status='ok',latency_ms=10,output_bytes=30,actual_credits=1,execution_usage=measured)
    report=events.for_run(run_id,100,0)
    assert report['summary']['event_count']==1
    assert report['events'][0]['quantity']==3
    assert report['events'][0]['unit']=='provider_credit'
    assert report['summary']['cost_state']=='unknown'
    assert report['summary']['unknown_event_count']==1
    assert report['summary']['total_cost_usd'] is None
    assert report['summary']['known_cost_subtotal_usd'] is None
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT actual_cost_internal FROM ih_runs WHERE id=%s',(run_id,))
        assert cur.fetchone()['actual_cost_internal'] is None


def test_rollback_unknown_usage_zero_units_and_historical_import(costs):
    control,events,run_id=costs
    assert events.for_run(run_id,100,0)['summary']['cost_state']=='unknown'
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO ih_provider_usage(id,request_id,provider,operation,status,credits_used) VALUES ('rolled-back',%s,'test','scrape','ok',2)",(run_id,))
        conn.rollback()
    assert events.for_run(run_id,100,0)['summary']['event_count']==0
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO ih_provider_usage(id,request_id,provider,operation,status,credits_used) VALUES (%s,%s,'test','scrape','ok',0)",('zero_'+uuid.uuid4().hex,run_id))
        cur.execute("INSERT INTO ih_provider_usage(id,request_id,provider,operation,status) VALUES (%s,%s,'test','scrape','ok')",('unknown_'+uuid.uuid4().hex,run_id))
    report=events.for_run(run_id,100,0)
    assert report['summary']['event_count']==1 and report['events'][0]['quantity']==0
    assert report['summary']['total_cost_usd'] is None
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('DELETE FROM ih_cost_events WHERE run_id=%s',(run_id,))
    other=ControlStore(control.dsn)
    other.ensure_schema()
    imported=CostEventStore(other).for_run(run_id,100,0)
    assert imported['summary']['event_count']==1
    assert imported['events'][0]['source']=='provider_reported'
    with pytest.raises(ControlError):
        events.for_run('missing',100,0)


def test_internal_economics_requires_operator_token(costs, monkeypatch):
    from internet_hands import cost_events_api
    _,events,run_id=costs
    monkeypatch.setattr(cost_events_api,'costs',events)
    monkeypatch.setenv('CRON_SECRET','operator-secret')
    app=FastAPI()
    app.include_router(cost_events_api.router)
    client=TestClient(app)
    path='/api/internal/runs/'+run_id+'/economics'
    assert client.get(path).status_code in (401,403)
    assert client.get(path,headers={'Authorization':'Bearer customer-key'}).status_code in (401,403)
    response=client.get(path,headers={'Authorization':'Bearer operator-secret'})
    assert response.status_code==200
    assert response.headers['Cache-Control']=='no-store'
    assert response.json()['summary']['cost_state']=='unknown'
