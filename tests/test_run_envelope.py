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
    finally:
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute('DELETE FROM ih_users WHERE id=%s', (owner,))
