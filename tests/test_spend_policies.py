import uuid

import pytest
from test_crawl_runs import runs  # noqa: F401 -- isolated PostgreSQL fixture

from internet_hands.control_store import ControlError
from internet_hands.spend_policies import SpendPolicyStore


def limits(**changes):
    return {'single_run_limit_credits':None,'daily_limit_credits':None,
            'monthly_limit_credits':None,'expected_version':0,**changes}


def test_account_policy_denies_work_without_reserving_or_inserting_a_run(request):
    jobs,identity=request.getfixturevalue('runs')
    policies=SpendPolicyStore(jobs.control)
    policies.put(identity.user_id,'account',limits(daily_limit_credits=0))
    with pytest.raises(ControlError) as error:
        jobs.create(identity,'blocked-by-policy',{'url':'https://example.com'})
    assert error.value.code=='spend_policy_exceeded'
    assert jobs.list(identity.user_id,10,0)['total']==0
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT count(*) AS n FROM ih_usage_events WHERE user_id=%s',(identity.user_id,))
        assert cur.fetchone()['n']==0
        cur.execute('SELECT reserved_credits FROM ih_wallets WHERE user_id=%s',(identity.user_id,))
        assert cur.fetchone()['reserved_credits']==0


def new_request_id():
    return 'req_'+uuid.uuid4().hex


def reserve(control,identity,arguments=None,tool='playground:crawl'):
    run=new_request_id()
    amount=control.reserve_tool_call(identity=identity,request_id=run,tool_name=tool,arguments=arguments or {},input_bytes=0)
    return run,amount


def test_reservations_consume_caps_and_partial_settlement_releases_headroom(request):
    jobs,identity=request.getfixturevalue('runs')
    control=jobs.control; policies=SpendPolicyStore(control)
    policies.put(identity.user_id,'account',limits(daily_limit_credits=12))
    research={'query':'example','max_pages':4,'paid_recovery':False}
    run,amount=reserve(control,identity,research,tool='playground:research')
    assert amount==9
    pending=policies.get(identity.user_id)['usage']['daily']
    assert pending['reserved_credits']==9 and pending['charged_credits']==0 and pending['remaining_credits']==3
    with pytest.raises(ControlError,match='daily limit'):
        reserve(control,identity,research,tool='playground:research')
    control.settle_tool_call(run,status='ok',latency_ms=1,output_bytes=0,actual_credits=1)
    control.settle_tool_call(run,status='ok',latency_ms=1,output_bytes=0,actual_credits=1)
    done=policies.get(identity.user_id)['usage']['daily']
    assert done['charged_credits']==3 and done['reserved_credits']==0
    assert done['remaining_credits']==9
    second,_=reserve(control,identity,research,tool='playground:research')
    control.release_tool_reservation(second,status='cancelled')
    assert policies.get(identity.user_id)['usage']['daily']['remaining_credits']==9


def add_key(control,owner):
    key='key_'+uuid.uuid4().hex
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO ih_api_keys(id,user_id,name,prefix,key_hash,scopes) VALUES (%s,%s,'Fixture','ih_live',%s,'[\"mcp:execute\"]')",
            (key,owner,uuid.uuid4().hex))
    return key


def test_account_and_key_limits_both_apply_and_session_cannot_bypass_account_cap(request):
    from dataclasses import replace
    jobs,identity=request.getfixturevalue('runs')
    control=jobs.control;policies=SpendPolicyStore(control)
    key=add_key(control,identity.user_id)
    other=add_key(control,identity.user_id)
    keyed=replace(identity,api_key_id=key,source='api_key')
    policies.put(identity.user_id,'account',limits(monthly_limit_credits=6))
    policies.put(identity.user_id,key,limits(daily_limit_credits=3))
    reserve(control,keyed)
    with pytest.raises(ControlError,match='daily limit'):
        reserve(control,keyed,{'max_charge_credits':1000000})
    reserve(control,replace(identity,api_key_id=other))
    with pytest.raises(ControlError,match='monthly limit'):
        reserve(control,identity)
    assert policies.get(identity.user_id,key)['usage']['daily']['committed_credits']==3
    assert policies.get(identity.user_id,'account')['usage']['monthly']['committed_credits']==6


def test_concurrent_admissions_cannot_overspend_the_shared_cap(request):
    from concurrent.futures import ThreadPoolExecutor
    jobs,identity=request.getfixturevalue('runs')
    policies=SpendPolicyStore(jobs.control)
    policies.put(identity.user_id,'account',limits(daily_limit_credits=8))
    def submit(_):
        try:
            return reserve(jobs.control,identity)
        except ControlError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(submit,range(4)))
    assert len([item for item in results if isinstance(item,tuple)])==2
    assert results.count('spend_policy_exceeded')==2
    assert policies.get(identity.user_id)['usage']['daily']['committed_credits']==6


def test_utc_windows_exclude_other_periods_future_events_and_foreign_accounts(request):
    from datetime import UTC, datetime, timedelta
    jobs,identity=request.getfixturevalue('runs')
    control=jobs.control; policies=SpendPolicyStore(control)
    end=datetime(2027,1,1,12,tzinfo=UTC)
    policies.put(identity.user_id,'account',limits(daily_limit_credits=50,monthly_limit_credits=60))
    key=add_key(control,identity.user_id)
    foreign='foreign_'+uuid.uuid4().hex
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('INSERT INTO ih_users(id,email) VALUES (%s,%s)',(foreign,foreign+'@test.invalid'))
        for owner,delta,status,charge,metadata in [
            (identity.user_id,timedelta(hours=1),'ok',7,'{}'),
            (identity.user_id,timedelta(hours=2),'reserved',0,'{"reservation":{"credits":9}}'),
            (identity.user_id,timedelta(days=1),'ok',100,'{}'),
            (identity.user_id,timedelta(seconds=-1),'ok',200,'{}'),
            (foreign,timedelta(hours=1),'ok',300,'{}'),
        ]:
            cur.execute('''INSERT INTO ih_usage_events(id,user_id,api_key_id,request_id,status,credits_charged,metadata,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s)''',
                (uuid.uuid4().hex,owner,key if owner==identity.user_id else None,new_request_id(),status,charge,metadata,end-delta))
    try:
        report=policies.get(identity.user_id,as_of=end)
        assert report['usage']['timezone']=='UTC'
        assert report['usage']['daily']['committed_credits']==16
        assert report['usage']['monthly']['committed_credits']==16
        assert report['usage']['day_start']==datetime(2027,1,1,tzinfo=UTC)
        assert report['usage']['month_end']==datetime(2027,2,1,tzinfo=UTC)
        assert policies.get(identity.user_id,key,as_of=end)['usage']['daily']['committed_credits']==16
        previous=policies.get(identity.user_id,as_of=end-timedelta(days=1))
        assert previous['usage']['month_start']==datetime(2026,12,1,tzinfo=UTC)
    finally:
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute('DELETE FROM ih_users WHERE id=%s',(foreign,))


@pytest.mark.parametrize('cancel',[True,False])
def test_accepted_job_survives_lowered_cap_and_idempotent_retry(request,cancel):
    jobs,identity=request.getfixturevalue('runs')
    policies=SpendPolicyStore(jobs.control)
    row=jobs.create(identity,'original',{'url':'https://example.com'})
    policies.put(identity.user_id,'account',limits(single_run_limit_credits=0,daily_limit_credits=0))
    assert jobs.create(identity,'original',{'url':'https://example.com'})['id']==row['id']
    with pytest.raises(ControlError,match='per-run limit'):
        jobs.create(identity,'new',{'url':'https://example.com'})
    if cancel:
        assert jobs.cancel(identity.user_id,row['id'])['status']=='cancelled'
    else:
        job=jobs.claim()
        assert jobs.finish(job,'completed',{'pages':[{'url':'https://example.com','status_code':200}]},{})
        assert jobs.get(identity.user_id,row['id'])['credits_charged']==3
    assert policies.get(identity.user_id)['usage']['daily']['reserved_credits']==0


def test_stale_policy_updates_are_rejected_and_caps_can_be_disabled(request):
    jobs,identity=request.getfixturevalue('runs')
    policies=SpendPolicyStore(jobs.control)
    first=policies.put(identity.user_id,'account',limits(daily_limit_credits=0))
    with pytest.raises(ControlError) as error:
        policies.put(identity.user_id,'account',limits(daily_limit_credits=100))
    assert error.value.code=='spend_policy_changed'
    disabled=policies.put(identity.user_id,'account',limits(expected_version=first['policy']['version']))
    assert disabled['policy']['daily_limit_credits'] is None
    reserve(jobs.control,identity)


@pytest.mark.parametrize('change',[
    {'daily_limit_credits':True},{'monthly_limit_credits':1.5},{'single_run_limit_credits':-1},
    {'daily_limit_credits':'100'},{'daily_limit_credits':1000000001},{'expected_version':None},
    {'expected_version':False},{'owner':'foreign'},
])
def test_invalid_policy_values_never_replace_the_policy(request,change):
    jobs,identity=request.getfixturevalue('runs')
    policies=SpendPolicyStore(jobs.control)
    with pytest.raises(ControlError) as error:
        policies.put(identity.user_id,'account',limits(**change))
    assert error.value.status_code==422
    assert policies.get(identity.user_id)['policy']['version']==0


def test_unknown_legacy_reservation_fails_closed_for_configured_period_caps(request):
    jobs,identity=request.getfixturevalue('runs')
    policies=SpendPolicyStore(jobs.control)
    policies.put(identity.user_id,'account',limits(daily_limit_credits=100))
    with jobs.control._connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO ih_usage_events(id,user_id,request_id,status) VALUES (%s,%s,%s,'reserved')",
            (uuid.uuid4().hex,identity.user_id,new_request_id()))
    report=policies.get(identity.user_id)
    assert report['usage']['daily']['unknown_reservation_count']==1
    assert report['usage']['daily']['remaining_credits'] is None
    with pytest.raises(ControlError) as error:
        reserve(jobs.control,identity)
    assert error.value.code=='spend_usage_unavailable'


def test_policy_api_is_session_owned_private_and_rejects_foreign_keys(request,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from internet_hands import control_api, spend_policy_api
    from internet_hands.auth import sha256_text
    jobs,identity=request.getfixturevalue('runs')
    control=jobs.control
    monkeypatch.setattr(control_api,'store',control)
    monkeypatch.setattr(spend_policy_api,'policies',SpendPolicyStore(control))
    raw='session_'+uuid.uuid4().hex
    control.create_session(user_id=identity.user_id,token_hash=sha256_text(raw))
    secret='ih_live_'+uuid.uuid4().hex
    key=control.create_api_key(user_id=identity.user_id,name='Controlled',prefix='ih_live',key_hash=sha256_text(secret),
        scopes=['mcp:execute','account:read'],environment='live')['id']
    assert control.authenticate_api_key(sha256_text(secret)) is not None
    app=FastAPI();app.include_router(spend_policy_api.router)
    client=TestClient(app)
    assert client.get('/api/spend-policy').status_code==401
    assert client.put('/api/spend-policy',headers={'Authorization':'Bearer '+secret},json=limits()).status_code==401
    client.cookies.set(control_api.SESSION_COOKIE,raw)
    get=client.get('/api/spend-policy')
    assert get.status_code==200 and get.headers['cache-control']=='no-store'
    assert get.json()['policy']['version']==0
    saved=client.put('/api/spend-policy',json=limits(monthly_limit_credits=10))
    assert saved.status_code==200 and saved.json()['policy']['version']==1
    assert saved.json()['wallet_units_per_usd']==5000
    keypath=f'/api/api-keys/{key}/spend-policy'
    assert client.put(keypath,json=limits(daily_limit_credits=0)).status_code==200
    assert client.get(keypath).json()['policy']['daily_limit_credits']==0
    assert client.get('/api/api-keys/foreign/spend-policy').status_code==404
    assert client.get('/api/api-keys/account/spend-policy').status_code==404
    assert client.put('/api/api-keys/account/spend-policy',json=limits()).status_code==404
    assert client.put('/api/api-keys/foreign/spend-policy',json=limits()).status_code==404
    assert client.put('/api/spend-policy',json=limits()).status_code==409
    assert client.put('/api/spend-policy',content='bad-json').status_code==400
    assert client.put('/api/spend-policy',content=' '*4097).status_code==413
    assert client.put('/api/spend-policy',json=[]).status_code==422
    assert 'provider' not in str(saved.json()) and 'unit_cost_usd' not in str(saved.json())


def test_reservation_rollback_and_schema_reinstall_keep_authoritative_headroom(request):
    from internet_hands.control_store import ControlStore
    jobs,identity=request.getfixturevalue('runs')
    policies=SpendPolicyStore(jobs.control)
    original=policies.put(identity.user_id,'account',limits(daily_limit_credits=3))
    with jobs.control._connect() as conn:
        jobs.control.reserve_tool_call(identity=identity,request_id=new_request_id(),tool_name='playground:crawl',
            arguments={},input_bytes=0,transaction=conn)
        conn.rollback()
    after=policies.get(identity.user_id)
    assert after['usage']['daily']['committed_credits']==0
    other=SpendPolicyStore(ControlStore(jobs.control.dsn))
    assert other.get(identity.user_id)['policy']==original['policy']
    reserve(jobs.control,identity)
    assert other.get(identity.user_id)['usage']['daily']['remaining_credits']==0


def test_concurrent_policy_writes_do_not_silently_replace_each_other(request):
    from concurrent.futures import ThreadPoolExecutor
    jobs,identity=request.getfixturevalue('runs')
    policies=SpendPolicyStore(jobs.control)
    def save(limit):
        try:
            return policies.put(identity.user_id,'account',limits(daily_limit_credits=limit))['policy']['version']
        except ControlError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(save,[3,6]))
    assert sorted(map(str,results))==['1','spend_policy_changed']


def test_applied_policy_revision_is_recorded_without_changing_quote_pricing(request):
    jobs,identity=request.getfixturevalue('runs')
    control=jobs.control; policies=SpendPolicyStore(control)
    before=control.quote_tool_call(identity=identity,tool_name='playground:crawl',arguments={})
    policies.put(identity.user_id,'account',limits(daily_limit_credits=3))
    after=control.quote_tool_call(identity=identity,tool_name='playground:crawl',arguments={})
    assert after==before
    run,_=reserve(control,identity,{'quote_revision':before['quote_revision'],'max_charge_credits':3})
    policies.put(identity.user_id,'account',limits(daily_limit_credits=0,expected_version=1))
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT metadata FROM ih_usage_events WHERE request_id=%s',(run,))
        recorded=cur.fetchone()['metadata']['budget']['spend_policies']
    assert recorded==[{'scope_id':'account','version':1,'single_run_limit_credits':None,
                      'daily_limit_credits':3,'monthly_limit_credits':None}]


def test_foreign_owned_key_cannot_be_read_or_reconfigured(request):
    jobs,identity=request.getfixturevalue('runs')
    control=jobs.control; policies=SpendPolicyStore(control)
    foreign='foreign_'+uuid.uuid4().hex
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('INSERT INTO ih_users(id,email) VALUES (%s,%s)',(foreign,foreign+'@test.invalid'))
    try:
        key=add_key(control,foreign)
        with pytest.raises(ControlError) as error:
            policies.get(identity.user_id,key)
        assert error.value.status_code==404
        with pytest.raises(ControlError) as error:
            policies.put(identity.user_id,key,limits(daily_limit_credits=0))
        assert error.value.status_code==404
    finally:
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute('DELETE FROM ih_users WHERE id=%s',(foreign,))


def test_zero_caps_allow_unbilled_tools_and_stale_release_restores_headroom(request):
    from datetime import UTC, datetime, timedelta
    jobs,identity=request.getfixturevalue('runs')
    control=jobs.control;policies=SpendPolicyStore(control)
    policies.put(identity.user_id,'account',limits(single_run_limit_credits=0,daily_limit_credits=0,monthly_limit_credits=0))
    run,amount=reserve(control,identity,tool='account_balance')
    assert amount==0
    control.release_tool_reservation(run)
    policies.put(identity.user_id,'account',limits(daily_limit_credits=3,expected_version=1))
    stale,_=reserve(control,identity)
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('UPDATE ih_usage_events SET created_at=%s WHERE request_id=%s',
            (datetime.now(UTC)-timedelta(hours=2),stale))
    released=control.release_stale_reservations(identity.user_id)
    assert released['reservations_released']==1 and released['credits_released']==3
    reserve(control,identity)
    assert policies.get(identity.user_id)['usage']['daily']['committed_credits']==3
