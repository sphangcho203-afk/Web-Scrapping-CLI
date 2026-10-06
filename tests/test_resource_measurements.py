"""Resource evidence uses real persistence, without inferring infrastructure expense."""
import pytest
from test_dataset_webhooks import postgres_webhooks as _postgres_webhooks

from internet_hands.cost_events import CostEventStore


@pytest.fixture
def postgres_webhooks(monkeypatch):
    yield from _postgres_webhooks.__wrapped__(monkeypatch)


def test_saved_payload_is_measured_from_stored_unicode_json(postgres_webhooks):
    control, _, _, _, save = postgres_webhooks
    dataset = save()
    report = CostEventStore(control).for_run(dataset['request_id'], 100, 0)
    assert report['coverage']['storage']['state'] == 'partial'
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT columns::text,rows::text,output::text FROM ih_datasets WHERE id=%s', (dataset['id'],))
        stored = cur.fetchone()
    expected = sum(len(value.encode('utf-8')) for value in stored.values())
    assert report['coverage']['storage']['observed_jsonb_utf8_bytes'] == expected
    assert report['coverage']['storage']['insert_observation_count'] == 1
    assert report['coverage']['browser']['state'] == 'not_instrumented'
    assert report['summary']['total_cost_usd'] is None
    assert report['summary']['coverage'] == 'partial'


@pytest.mark.asyncio
async def test_dispatch_intent_and_outcome_count_exact_application_bytes(postgres_webhooks, monkeypatch):
    from internet_hands import dataset_webhooks

    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive', True)
    dataset = save()
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_dataset_webhook_deliveries SET body=replace(body,%s,%s) || %s WHERE dataset_id=%s",
                    ('"crawl"', '"অসম"', '\n \t', dataset['id']))
    sent = []

    async def receiver(url, body, headers):
        sent.append(body)
        return 204

    monkeypatch.setattr(dataset_webhooks, 'send_webhook', receiver)
    await dataset_webhooks.dispatch_webhooks(hooks)
    delivery = CostEventStore(control).for_run(dataset['request_id'], 100, 0)['coverage']['delivery']
    assert delivery['state'] == 'partial'
    assert delivery['claim_count'] == delivery['dispatch_intent_count'] == delivery['outcome_count'] == 1
    assert delivery['dispatch_intent_payload_utf8_bytes'] == len(sent[0])
    assert len(sent[0]) > len(sent[0].decode('utf-8')) and sent[0].endswith(b'\n \t')
    assert delivery['delivered_count'] == 1


def test_duplicate_save_and_rename_preserve_the_original_observation(postgres_webhooks):
    from internet_hands.datasets import DatasetStore

    control, _, owner, _, save = postgres_webhooks
    dataset = save()
    before = CostEventStore(control).for_run(dataset['request_id'], 100, 0)['coverage']['storage']
    assert save()['id'] == dataset['id']
    DatasetStore(control).rename(owner, dataset['id'], 'A much longer renamed dataset অসম')
    assert CostEventStore(control).for_run(dataset['request_id'], 100, 0)['coverage']['storage'] == before


def test_outbox_failure_rolls_back_payload_evidence(postgres_webhooks, monkeypatch):
    from internet_hands import datasets

    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive', True)

    def fail(*args):
        raise RuntimeError('outbox failure')

    monkeypatch.setattr(datasets, 'enqueue_dataset_event', fail)
    with pytest.raises(RuntimeError, match='outbox failure'):
        save()
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('''SELECT count(*) AS count FROM ih_dataset_payload_measurements m
            JOIN ih_runs r ON r.id=m.run_id WHERE r.user_id=%s''', (owner,))
        assert cur.fetchone()['count'] == 0
    assert datasets.DatasetStore(control).list(owner, limit=25, offset=0)['total'] == 0
    assert hooks.history(owner)['total'] == 0


def test_claim_evidence_rolls_back_with_the_lease(postgres_webhooks):
    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive', True)
    dataset = save()
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("""UPDATE ih_dataset_webhook_deliveries SET status='delivering',attempts=1,
            lease_token='rolled_back',lease_until=now()+interval '60 seconds' WHERE dataset_id=%s""", (dataset['id'],))
        cur.execute('SELECT count(*) AS count FROM ih_webhook_attempt_measurements WHERE run_id=%s', (dataset['request_id'],))
        assert cur.fetchone()['count'] == 1
        conn.rollback()
    assert hooks.history(owner)['deliveries'][0]['status'] == 'pending'
    report = CostEventStore(control).for_run(dataset['request_id'], 100, 0)['coverage']['delivery']
    assert report['claim_count'] == 0 and report['current_delivery_without_journal_count'] == 1


def test_existing_snapshot_backfill_is_idempotent_and_does_not_invent_attempts(postgres_webhooks):
    from internet_hands.control_store import ControlStore

    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive', True)
    dataset = save()
    with control._connect() as conn, conn.cursor() as cur:
        # Simulate a surviving pre-instrumentation artifact and delivered outbox.
        cur.execute('DELETE FROM ih_dataset_payload_measurements WHERE dataset_id=%s', (dataset['id'],))
        cur.execute("UPDATE ih_datasets SET created_at='2020-01-01' WHERE id=%s", (dataset['id'],))
        cur.execute("UPDATE ih_dataset_webhook_deliveries SET status='delivered',attempts=3 WHERE dataset_id=%s", (dataset['id'],))
    migrated = ControlStore(control.dsn)
    migrated.ensure_schema()
    store = CostEventStore(migrated)
    before = store.for_run(dataset['request_id'], 100, 0)
    assert before['coverage']['storage']['existing_snapshot_count'] == 1
    assert before['coverage']['storage']['insert_observation_count'] == 0
    assert before['coverage']['delivery']['claim_count'] == 0
    assert before['coverage']['delivery']['current_delivery_without_journal_count'] == 1
    with migrated._connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT observed_at>created_at AS later FROM ih_dataset_payload_measurements m '
                    'JOIN ih_datasets d ON d.id=m.dataset_id WHERE d.id=%s', (dataset['id'],))
        assert cur.fetchone()['later']
    ControlStore(control.dsn).ensure_schema()
    assert store.for_run(dataset['request_id'], 100, 0) == before


def test_concurrent_intents_and_duplicate_outcomes_are_idempotent(postgres_webhooks):
    from concurrent.futures import ThreadPoolExecutor

    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive', True)
    dataset = save()
    event = hooks.claim()[0]
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(lambda _: hooks.begin_attempt(event), range(2))) == [False, True]
    hooks.finish(event, http_status=503, error='Receiver returned HTTP 503.')
    hooks.finish(event, http_status=204, error=None)
    delivery = CostEventStore(control).for_run(dataset['request_id'], 100, 0)['coverage']['delivery']
    assert delivery['claim_count'] == delivery['dispatch_intent_count'] == delivery['outcome_count'] == 1
    assert delivery['retry_count'] == 1 and delivery['delivered_count'] == 0
    assert hooks.history(owner)['deliveries'][0]['status'] == 'retry'


def test_expired_lease_cannot_start_but_its_late_outcome_preserves_evidence(postgres_webhooks):
    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive', True)
    dataset = save()
    old = hooks.claim()[0]
    assert hooks.begin_attempt(old)
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_dataset_webhook_deliveries SET lease_until=now()-interval '1 minute' WHERE id=%s", (old['id'],))
    assert not hooks.begin_attempt(old)
    new = hooks.claim()[0]
    assert hooks.begin_attempt(new)
    hooks.finish(old, http_status=204, error=None)
    assert hooks.history(owner)['deliveries'][0]['status'] == 'delivering'
    hooks.finish(new, http_status=204, error=None)
    delivery = CostEventStore(control).for_run(dataset['request_id'], 100, 0)['coverage']['delivery']
    assert delivery['claim_count'] == delivery['dispatch_intent_count'] == delivery['outcome_count'] == 2
    assert delivery['delivered_count'] == 2  # Two observed responses, one outbox delivery.


@pytest.mark.parametrize('had_intent', [False, True])
def test_recovered_lease_keeps_the_abandoned_claim_unknown(postgres_webhooks, had_intent):
    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive', True)
    dataset = save()
    old = hooks.claim()[0]
    if had_intent:
        assert hooks.begin_attempt(old)
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_dataset_webhook_deliveries SET lease_until=now()-interval '1 minute' WHERE id=%s", (old['id'],))
    new = hooks.claim()[0]
    assert not hooks.begin_attempt(old) and hooks.begin_attempt(new)
    hooks.finish(new, http_status=204, error=None)
    delivery = CostEventStore(control).for_run(dataset['request_id'], 100, 0)['coverage']['delivery']
    assert delivery['claim_count'] == 2 and delivery['outcome_count'] == 1
    assert delivery['unknown_outcome_count'] == 1
    assert delivery['claim_without_intent_count'] == int(not had_intent)
    assert delivery['unfinished_intent_count'] == int(had_intent)


def test_manual_retry_reset_creates_a_distinct_attempt_without_new_billing(postgres_webhooks):
    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive', True)
    dataset = save()
    first = hooks.claim()[0]
    assert hooks.begin_attempt(first)
    hooks.finish(first, http_status=401, error='Receiver returned HTTP 401.', permanent=True)
    hooks.retry(owner, first['id'])
    second = hooks.claim()[0]
    assert first['id'] == second['id'] and first['attempts'] == second['attempts'] == 1
    assert hooks.begin_attempt(second)
    hooks.finish(second, http_status=204, error=None)
    delivery = CostEventStore(control).for_run(dataset['request_id'], 100, 0)['coverage']['delivery']
    assert delivery['claim_count'] == 2 and delivery['failed_count'] == delivery['delivered_count'] == 1
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT count(*) AS count FROM ih_usage_events WHERE user_id=%s', (owner,))
        assert cur.fetchone()['count'] == 1


async def test_failed_outcome_write_remains_unknown_after_successful_recovery(postgres_webhooks, monkeypatch):
    from internet_hands import dataset_webhooks

    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive', True)
    dataset = save()
    sent = []

    async def receiver(url, body, headers):
        sent.append(body)
        return 204

    def unavailable(*args, **kwargs):
        raise RuntimeError('outcome store unavailable')

    finish = hooks.finish
    monkeypatch.setattr(dataset_webhooks, 'send_webhook', receiver)
    monkeypatch.setattr(hooks, 'finish', unavailable)
    result = await dataset_webhooks.dispatch_webhooks(hooks)
    assert 'outcome could not be recorded' in result['deliveries'][0]['error']
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_dataset_webhook_deliveries SET lease_until=now()-interval '1 minute' WHERE dataset_id=%s", (dataset['id'],))
    monkeypatch.setattr(hooks, 'finish', finish)
    await dataset_webhooks.dispatch_webhooks(hooks)
    delivery = CostEventStore(control).for_run(dataset['request_id'], 100, 0)['coverage']['delivery']
    assert len(sent) == 2 and sent[0] == sent[1]
    assert delivery['dispatch_intent_payload_utf8_bytes'] == sum(map(len, sent))
    assert delivery['claim_count'] == delivery['dispatch_intent_count'] == 2
    assert delivery['outcome_count'] == delivery['unknown_outcome_count'] == 1


async def test_expired_dispatch_claim_never_calls_sender(postgres_webhooks, monkeypatch):
    from internet_hands import dataset_webhooks

    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive', True)
    dataset = save()
    claim = hooks.claim

    def expired_claim(limit):
        events = claim(limit)
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE ih_dataset_webhook_deliveries SET lease_until=now()-interval '1 minute' WHERE dataset_id=%s", (dataset['id'],))
        return events

    async def forbidden(*args):
        pytest.fail('Expired lease must not invoke the sender')

    monkeypatch.setattr(hooks, 'claim', expired_claim)
    monkeypatch.setattr(dataset_webhooks, 'send_webhook', forbidden)
    await dataset_webhooks.dispatch_webhooks(hooks)
    delivery = CostEventStore(control).for_run(dataset['request_id'], 100, 0)['coverage']['delivery']
    assert delivery['claim_count'] == delivery['unknown_outcome_count'] == 1
    assert delivery['dispatch_intent_count'] == delivery['outcome_count'] == 0


async def test_policy_rejection_is_an_intent_without_measured_wire_egress(postgres_webhooks, monkeypatch):
    from internet_hands import dataset_webhooks
    from internet_hands.policy import PolicyError

    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive?token=private', True)
    dataset = save()

    def reject(*args):
        raise PolicyError('Rejected private target with private token')

    monkeypatch.setattr(dataset_webhooks, 'resolve_public_http_url', reject)
    result = await dataset_webhooks.dispatch_webhooks(hooks)
    assert 'private' not in str(result)
    delivery = CostEventStore(control).for_run(dataset['request_id'], 100, 0)['coverage']['delivery']
    assert delivery['claim_count'] == delivery['dispatch_intent_count'] == delivery['failed_count'] == 1
    assert delivery['outcome_without_http_status_count'] == 1 and delivery['valuation_state'] == 'unknown'


@pytest.mark.parametrize('remove', ['dataset', 'endpoint', 'history'])
async def test_cleanup_keeps_audit_facts_but_account_deletion_removes_them(postgres_webhooks, monkeypatch, remove):
    from internet_hands import dataset_webhooks
    from internet_hands.control_store import ControlStore
    from internet_hands.datasets import DatasetStore

    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive', True)
    dataset = save()

    async def receiver(*args):
        return 204

    monkeypatch.setattr(dataset_webhooks, 'send_webhook', receiver)
    await dataset_webhooks.dispatch_webhooks(hooks)
    store = CostEventStore(control)
    before = store.for_run(dataset['request_id'], 100, 0)['coverage']
    if remove == 'dataset':
        DatasetStore(control).delete(owner, dataset['id'])
    elif remove == 'endpoint':
        hooks.delete_endpoint(owner)
    else:
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE ih_dataset_webhook_deliveries SET created_at=now()-interval '31 days' WHERE dataset_id=%s", (dataset['id'],))
        assert hooks.claim() == []
    ControlStore(control.dsn).ensure_schema()
    after = store.for_run(dataset['request_id'], 100, 0)['coverage']
    assert hooks.history(owner)['total'] == 0
    assert after['delivery'] == before['delivery']
    assert after['storage']['observed_jsonb_utf8_bytes'] == before['storage']['observed_jsonb_utf8_bytes']
    assert after['storage']['current_observed_dataset_count'] == int(remove != 'dataset')
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute('DELETE FROM ih_users WHERE id=%s', (owner,))
        for table in ('ih_dataset_payload_measurements', 'ih_webhook_attempt_measurements'):
            cur.execute(f'SELECT count(*) AS count FROM {table} WHERE run_id=%s', (dataset['request_id'],))
            assert cur.fetchone()['count'] == 0


def test_measurement_and_recorded_outcome_cannot_be_overwritten(postgres_webhooks):
    from psycopg.errors import RaiseException

    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive', True)
    dataset = save()
    event = hooks.claim()[0]
    assert hooks.begin_attempt(event)
    hooks.finish(event, http_status=204, error=None)
    with control._connect() as conn, conn.cursor() as cur:
        for statement, args in [
            ('UPDATE ih_dataset_payload_measurements SET jsonb_utf8_bytes=0 WHERE dataset_id=%s', (dataset['id'],)),
            ('UPDATE ih_webhook_attempt_measurements SET payload_utf8_bytes=0 WHERE delivery_id=%s', (event['id'],)),
            ("UPDATE ih_webhook_attempt_measurements SET outcome='failed',http_status=503 WHERE delivery_id=%s", (event['id'],)),
            ('UPDATE ih_webhook_attempt_measurements SET dispatch_intent_at=NULL WHERE delivery_id=%s', (event['id'],)),
        ]:
            with pytest.raises(RaiseException), conn.transaction():
                cur.execute(statement, args)


def test_operator_resource_coverage_is_private_and_precision_preserving(postgres_webhooks, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from internet_hands import cost_events_api
    from internet_hands.control_store import ControlError
    from internet_hands.run_envelope import RunEnvelopeStore

    control, hooks, owner, foreign, save = postgres_webhooks
    secret = hooks.configure(owner, 'https://hooks.example.com/receive?token=private', True)['signing_secret']
    dataset = save()
    event = hooks.claim()[0]
    assert hooks.begin_attempt(event)
    hooks.finish(event, http_status=204, error=None)
    monkeypatch.setattr(cost_events_api, 'costs', CostEventStore(control))
    monkeypatch.setenv('CRON_SECRET', 'isolated-operator-secret')
    app = FastAPI()
    app.include_router(cost_events_api.router)
    client = TestClient(app)
    path = '/api/internal/runs/' + dataset['request_id'] + '/economics'
    assert client.get(path).status_code == 401
    assert client.get(path, headers={'Authorization': 'Bearer customer-key'}).status_code == 401
    response = client.get(path, headers={'Authorization': 'Bearer isolated-operator-secret'})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert isinstance(response.json()['coverage']['storage']['observed_jsonb_utf8_bytes'], str)
    assert isinstance(response.json()['coverage']['delivery']['dispatch_intent_payload_utf8_bytes'], str)
    public = RunEnvelopeStore(control).get(owner, dataset['request_id'], 0, 100)
    for private in (secret, event['lease_token'], 'private', 'hooks.example.com', 'অসম', 'payload_utf8_bytes', 'observed_jsonb_utf8_bytes'):
        assert private not in str(public)
    for private in (secret, event['lease_token'], 'hooks.example.com', 'অসম'):
        assert private not in response.text
    with pytest.raises(ControlError) as denied:
        RunEnvelopeStore(control).get(foreign, dataset['request_id'], 0, 100)
    assert denied.value.status_code == 404


def test_report_reads_one_snapshot_while_a_delivery_finishes(postgres_webhooks, monkeypatch):
    from internet_hands import cost_events

    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive', True)
    dataset = save()
    event = hooks.claim()[0]
    read_coverage = cost_events.resource_coverage

    def finish_between_reads(cur, run_id):
        assert hooks.begin_attempt(event)
        hooks.finish(event, http_status=204, error=None)
        return read_coverage(cur, run_id)

    monkeypatch.setattr(cost_events, 'resource_coverage', finish_between_reads)
    store = CostEventStore(control)
    snapshot = store.for_run(dataset['request_id'], 100, 0)['coverage']['delivery']
    assert snapshot['claim_count'] == snapshot['unknown_outcome_count'] == 1
    assert snapshot['dispatch_intent_count'] == snapshot['outcome_count'] == 0
    monkeypatch.setattr(cost_events, 'resource_coverage', read_coverage)
    after = store.for_run(dataset['request_id'], 100, 0)['coverage']['delivery']
    assert after['dispatch_intent_count'] == after['outcome_count'] == 1


def test_lock_wait_uses_current_time_for_lease_authorization(postgres_webhooks):
    import time
    from concurrent.futures import ThreadPoolExecutor

    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive', True)
    save()
    event = hooks.claim()[0]
    with ThreadPoolExecutor(max_workers=1) as workers:
        with control._connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT id FROM ih_dataset_webhook_deliveries WHERE id=%s FOR UPDATE', (event['id'],))
            future = workers.submit(hooks.begin_attempt, event)
            try:
                # Wait for the worker transaction to block on our real row lock.
                deadline = time.monotonic() + 5
                waiting = None
                while not waiting and time.monotonic() < deadline:
                    cur.execute('SELECT pg_stat_clear_snapshot()')
                    cur.execute('SELECT xact_start FROM pg_stat_activity WHERE %s=ANY(pg_blocking_pids(pid))',
                                (conn.info.backend_pid,))
                    waiting = cur.fetchone()
                    if not waiting:
                        time.sleep(0.01)
                assert waiting
                cur.execute('''UPDATE ih_dataset_webhook_deliveries SET lease_until=clock_timestamp()
                    WHERE id=%s RETURNING lease_until''', (event['id'],))
                assert cur.fetchone()['lease_until'] > waiting['xact_start']
                conn.commit()
            finally:
                conn.rollback()  # Release the lock even if the test fails.
        assert future.result(timeout=5) is False


def test_failed_journal_write_rolls_back_the_outbox_outcome(postgres_webhooks):
    from psycopg.errors import CheckViolation

    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive', True)
    dataset = save()
    event = hooks.claim()[0]
    assert hooks.begin_attempt(event)
    # The journal rejects invalid status evidence after the outbox UPDATE.
    with pytest.raises(CheckViolation):
        hooks.finish(event, http_status=999, error='Invalid response status')
    assert hooks.history(owner)['deliveries'][0]['status'] == 'delivering'
    delivery = CostEventStore(control).for_run(dataset['request_id'], 100, 0)['coverage']['delivery']
    assert delivery['dispatch_intent_count'] == delivery['unknown_outcome_count'] == 1
    assert delivery['outcome_count'] == 0


async def test_preparation_failure_records_outcome_without_send_intent(postgres_webhooks, monkeypatch):
    from internet_hands import dataset_webhooks

    control, hooks, owner, _, save = postgres_webhooks
    hooks.configure(owner, 'https://hooks.example.com/receive', True)
    dataset = save()

    def decryption_failure(*args):
        raise RuntimeError('private secret preparation failure')

    async def forbidden(*args):
        pytest.fail('A preparation failure cannot invoke the sender')

    monkeypatch.setattr(dataset_webhooks, 'decrypt_secret', decryption_failure)
    monkeypatch.setattr(dataset_webhooks, 'send_webhook', forbidden)
    result = await dataset_webhooks.dispatch_webhooks(hooks)
    assert 'private' not in str(result)
    delivery = CostEventStore(control).for_run(dataset['request_id'], 100, 0)['coverage']['delivery']
    assert delivery['claim_count'] == delivery['outcome_count'] == delivery['retry_count'] == 1
    assert delivery['dispatch_intent_count'] == 0
