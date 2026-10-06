import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from internet_hands import runs_api
from internet_hands.control_store import ControlError, ControlStore
from internet_hands.run_envelope import RunEnvelopeStore


def test_run_api_owner_and_bounds(monkeypatch):
    class Receipts:
        def list(self, owner, limit, offset):
            assert owner == 'owner'
            return {'runs': [], 'total': 0}

        def get(self, owner, run_id, after, limit):
            assert owner == 'owner'
            raise ControlError('run_not_found', 'Run not found for this account.', 404)

    monkeypatch.setattr(runs_api, 'runs', Receipts())
    monkeypatch.setattr(runs_api, '_owner', lambda request: 'owner')
    app = FastAPI()
    app.include_router(runs_api.router)
    client = TestClient(app)
    assert client.get('/api/runs').json() == {'runs': [], 'total': 0}
    assert client.get('/api/runs/foreign').status_code == 404
    assert client.get('/api/runs?limit=101').status_code == 422
    assert client.get('/api/runs/one?after=-1').status_code == 422


def test_run_envelope_postgres_transaction_and_idempotency():
    dsn = os.getenv('OPENCRAWL_TEST_DATASET_DSN')
    if not dsn:
        pytest.skip('Requires isolated PostgreSQL')
    control = ControlStore(dsn)
    control.ensure_schema()
    suffix = uuid.uuid4().hex
    owner, request_id = 'owner_' + suffix, 'req_' + suffix
    runs = RunEnvelopeStore(control)
    try:
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute('INSERT INTO ih_users(id,email) VALUES (%s,%s)',
                        (owner, owner + '@test.invalid'))
            cur.execute("""INSERT INTO ih_usage_events(id,user_id,request_id,status,metadata)
                VALUES (%s,%s,%s,'reserved','{"reservation":{"credits":10}}')""",
                ('ev_' + suffix, owner, request_id))
        receipt = runs.get(owner, request_id, 0, 100)
        assert receipt['run']['credits_reserved'] == 10
        assert len(receipt['events']) == 1
        with pytest.raises(ControlError):
            runs.get('foreign', request_id, 0, 100)
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE ih_usage_events SET status='ok',credits_charged=3 WHERE request_id=%s",
                        (request_id,))
            cur.execute("UPDATE ih_usage_events SET status='ok',credits_charged=3 WHERE request_id=%s",
                        (request_id,))
        receipt = runs.get(owner, request_id, 0, 100)
        assert receipt['run']['credits_charged'] == 3
        assert [event['sequence'] for event in receipt['events']] == [1, 2]
        assert runs.get(owner, request_id, 1, 100)['events'][0]['sequence'] == 2
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE ih_usage_events SET credits_charged=9 WHERE request_id=%s", (request_id,))
            conn.rollback()
        assert len(runs.get(owner, request_id, 0, 100)['events']) == 2
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO ih_crawl_runs(id,user_id,request_id,idempotency_key,
                fingerprint,arguments,plan_slug,credits_reserved)
                VALUES (%s,%s,%s,%s,'fingerprint','{"url":"https://example.com"}','free',10)""",
                ('crawl_' + suffix, owner, request_id, suffix))
            cur.execute("UPDATE ih_crawl_runs SET status='running',attempts=1 WHERE request_id=%s",
                        (request_id,))
            cur.execute("UPDATE ih_crawl_runs SET cancel_requested=true WHERE request_id=%s",
                        (request_id,))
        receipt = runs.get(owner, request_id, 0, 100)
        assert [e['type'] for e in receipt['events']][-3:] == [
            'execution_created', 'execution_status', 'cancellation_requested']
        assert receipt['events'][-1]['attempt'] == 1
        assert receipt['run']['execution']['cancel_requested'] is True
        assert receipt['run']['credits_charged'] == 3
    finally:
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute('DELETE FROM ih_users WHERE id=%s', (owner,))


@pytest.fixture
def run_system():
    from internet_hands.control_store import AuthIdentity
    from internet_hands.crawl_runs import RunStore
    dsn = os.getenv('OPENCRAWL_TEST_DATASET_DSN')
    if not dsn:
        pytest.skip('Requires isolated PostgreSQL')
    control = ControlStore(dsn)
    control.ensure_schema()
    owner = 'canonical_' + uuid.uuid4().hex
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('INSERT INTO ih_users(id,email) VALUES (%s,%s)', (owner, owner+'@test.invalid'))
        cur.execute('INSERT INTO ih_wallets(user_id,monthly_credits) VALUES (%s,100000)', (owner,))
    identity = AuthIdentity(owner, None, ['mcp:execute'], 'free', 100, 'session', 10)
    try:
        yield RunStore(control), RunEnvelopeStore(control), identity
    finally:
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute('DELETE FROM ih_users WHERE id=%s', (owner,))


def test_normalized_lifecycle_retries_output_and_one_charge(run_system):
    from concurrent.futures import ThreadPoolExecutor
    jobs, receipts, identity = run_system
    with ThreadPoolExecutor(max_workers=4) as pool:
        originals = list(pool.map(lambda _: jobs.create(identity, 'same', {'url':'https://example.com'}), range(4)))
    original = originals[0]
    assert len({r['id'] for r in originals}) == 1
    request_id = original['request_id']
    initial = receipts.get(identity.user_id, original['id'], 0, 100)['run']
    assert initial['id'] == request_id
    assert initial['execution_status'] == 'queued'
    assert initial['source_count'] == 1
    assert initial['source_ref'] == original['id']
    assert receipts.list('foreign', 25, 0)['total'] == 0
    with pytest.raises(ControlError):
        receipts.get('foreign', original['id'], 0, 100)
    first = jobs.claim()
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_crawl_runs SET lease_until=now()-interval '1 second' WHERE id=%s", (original['id'],))
    second = jobs.claim()
    assert receipts.get(identity.user_id, request_id, 0, 100)['run']['retry_count'] == 1
    result = {'pages':[{'url':'https://example.com','status_code':200,'text':'saved'}]}
    assert not jobs.finish(first, 'completed', result, {'completed':True})
    assert jobs.finish(second, 'completed', result, {'completed':True})
    assert not jobs.finish(second, 'completed', {}, {})
    final = receipts.get(identity.user_id, request_id, 0, 100)
    assert final['run']['execution_status'] == 'completed'
    assert final['run']['output_dataset_id'] and final['run']['credits_charged'] > 0
    assert final['run']['started_at'] and final['run']['execution_finished_at']
    assert sum(e['type'] == 'billing_transition' for e in final['events']) == 1
    assert sum(e['type'] == 'output_saved' for e in final['events']) == 1
    assert [e['sequence'] for e in final['events']] == list(range(1,len(final['events'])+1))


def test_projection_rollback_partial_and_cancellation(run_system):
    jobs, receipts, identity = run_system
    original = jobs.create(identity, 'cancel', {'url':'https://example.com'})
    request_id = original['request_id']
    before = receipts.get(identity.user_id, request_id, 0, 100)
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_crawl_runs SET status='running',attempts=1 WHERE id=%s", (original['id'],))
        conn.rollback()
    assert receipts.get(identity.user_id, request_id, 0, 100) == before
    jobs.cancel(identity.user_id, original['id'])
    cancelled = receipts.get(identity.user_id, request_id, 0, 100)['run']
    assert cancelled['execution_status'] == 'cancelled'
    assert cancelled['cancel_requested'] and cancelled['credits_charged'] == 0
    original = jobs.create(identity, 'partial', {'url':'https://example.com'})
    job = jobs.claim()
    assert jobs.finish(job, 'completed', {'truncated':True,'pages':[{'url':'https://example.com','status_code':200,'text':'captured'}]}, {'completed':True})
    partial = receipts.get(identity.user_id, original['request_id'], 0, 100)['run']
    assert partial['status'] == 'ok' and partial['execution_status'] == 'partial'
    assert partial['warning_count'] == 1


def test_immediate_calls_hide_private_provider_attempt_data(run_system):
    jobs, receipts, identity = run_system
    request_id = 'req_' + uuid.uuid4().hex
    jobs.control.reserve_tool_call(identity=identity, request_id=request_id, tool_name='playground:search',input_bytes=50,
                                   arguments={'query':'private search','token':'secret'})
    jobs.control.settle_tool_call(request_id,status='ok',latency_ms=100,output_bytes=30,actual_credits=1,
        execution_usage={'provider_events':[{'provider':'secret-provider','ref':'internal:secret-ref',
            'status':'error','attempt':1,'error':'secret-password'},{'provider':'secret-provider',
            'ref':'internal:secret-ref','status':'ok','attempt':2}]})
    detail = receipts.get(identity.user_id, request_id, 0, 100)
    assert detail['run']['execution_status'] == 'completed'
    assert detail['run']['source_count'] is None
    attempts = [e for e in detail['events'] if e['type']=='provider_attempt']
    assert [e['attempt'] for e in attempts] == [1,2]
    assert all('secret' not in str(item) for item in (detail['run'],detail['events']))
    assert 'actual_cost_internal' not in detail['run']


def test_capability_waiting_and_cancel_bridge(run_system):
    from internet_hands.capability_runs import CapabilityRunStore
    jobs, receipts, identity = run_system
    capabilities = CapabilityRunStore(jobs.control)
    args = {'capability':'web.extract.structured','arguments':{'urls':['https://example.com'],
            'prompt':'Extract title','maxCredits':5}}
    original = capabilities.create(identity,'extract','web.extract.structured',args)
    request_id = original['request_id']
    job = capabilities.claim(original['id'])
    capabilities.wait_for_provider(job, provider='private-provider', provider_job_id='secret-job', usage={})
    waiting = receipts.get(identity.user_id, request_id, 0, 100)
    assert waiting['run']['execution_status']=='waiting'
    assert waiting['run']['source_count']==1
    assert waiting['run']['source_kind']=='capability'
    assert 'secret-job' not in str(waiting)
    with pytest.raises(ControlError) as already_started:
        capabilities.cancel(identity.user_id, original['id'])
    assert already_started.value.code == 'run_already_started'
    queued = capabilities.create(identity,'extract-cancel','web.extract.structured',args)
    capabilities.cancel(identity.user_id, queued['id'])
    assert receipts.get(identity.user_id, queued['request_id'], 0, 100)['run']['execution_status']=='cancelled'


def test_schema_reinstallation_preserves_events_and_imports_existing_receipt(run_system):
    jobs, receipts, identity = run_system
    original = jobs.create(identity, 'migrate', {'url':'https://example.com'})
    before = receipts.get(identity.user_id, original['request_id'], 0, 100)
    # A separate process may reinstall the idempotent additive migration.
    other = ControlStore(jobs.control.dsn)
    other.ensure_schema()
    after = RunEnvelopeStore(other).get(identity.user_id, original['request_id'], 0, 100)
    assert after == before


def test_run_api_scopes_cache_and_cancellation_ownership(run_system, monkeypatch):
    from dataclasses import replace

    from internet_hands import datasets_api
    jobs, receipts, identity = run_system
    original = jobs.create(identity, 'api-cancel', {'url':'https://example.com'})
    monkeypatch.setattr(runs_api, 'runs', receipts)
    monkeypatch.setattr(runs_api, 'store', jobs.control)
    tokens = {'read':replace(identity,scopes=['mcp:read']),
              'execute':replace(identity,scopes=['mcp:execute']),
              'both':replace(identity,scopes=['mcp:read','mcp:execute']),
              'foreign':replace(identity,user_id='foreign',scopes=['*'])}
    monkeypatch.setattr(datasets_api,'authenticate_secret',lambda store, secret: tokens.get(secret))
    app = FastAPI()
    app.include_router(runs_api.router)
    client = TestClient(app)
    base = '/api/runs/' + original['request_id']
    assert client.get(base,headers={'Authorization':'Bearer invalid'}).status_code==401
    assert client.get(base,headers={'Authorization':'Bearer execute'}).status_code==403
    read = client.get(base,headers={'Authorization':'Bearer read'})
    assert read.status_code==200 and read.headers['Cache-Control']=='no-store'
    assert client.post(base+'/cancel',headers={'Authorization':'Bearer read'}).status_code==403
    assert client.post(base+'/cancel',headers={'Authorization':'Bearer foreign'}).status_code==404
    cancel = client.post(base+'/cancel',headers={'Authorization':'Bearer both'})
    assert cancel.status_code==200 and cancel.json()['run']['execution_status']=='cancelled'


def test_historical_import_has_facts_without_invented_events(run_system):
    jobs, receipts, identity = run_system
    original = jobs.create(identity, 'historical', {'url':'https://example.com'})
    job = jobs.claim()
    assert jobs.finish(job,'completed',{'pages':[{'url':'https://example.com','status_code':200,'text':'history'}]}, {'completed':True})
    before = receipts.get(identity.user_id, original['request_id'], 0, 100)['run']
    # Simulate a pre-envelope deployment: source records exist but no receipt.
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute('DELETE FROM ih_runs WHERE id=%s', (original['request_id'],))
    other = ControlStore(jobs.control.dsn)
    other.ensure_schema()
    imported = RunEnvelopeStore(other).get(identity.user_id, original['request_id'], 0, 100)
    assert imported['events']==[]
    assert imported['run']['history_origin']=='snapshot'
    assert imported['run']['execution_status']=='completed'
    assert imported['run']['output_dataset_id']==before['output_dataset_id']
    assert imported['run']['credits_charged']==before['credits_charged']
    assert imported['run']['started_at'] is None
    assert imported['run']['execution_finished_at']==before['execution_finished_at']
