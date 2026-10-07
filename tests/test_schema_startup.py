"""Schema startup concurrency tests use only an explicitly isolated test database."""
from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from internet_hands import control_store
from internet_hands.control_store import ControlStore


@pytest.mark.parametrize("failure", ["schema", "commit"])
def test_failed_initialization_is_retryable_and_only_success_is_cached(monkeypatch, failure):
    store = ControlStore("postgresql://unused/test")
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    if failure == "schema":
        def execute(statement, *args):
            if statement == control_store.SCHEMA_SQL:
                raise RuntimeError("schema failed")
        cursor.execute.side_effect = execute
    else:
        connection.commit.side_effect = RuntimeError("commit failed")
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(store, "_connect", connect)
    with pytest.raises(RuntimeError):
        store.ensure_schema()
    assert not store._schema_ready
    cursor.execute.side_effect = None
    connection.commit.side_effect = None
    store.ensure_schema()
    assert store._schema_ready
    store.ensure_schema()
    assert connect.call_count == 2


@pytest.fixture
def isolated_schema():
    dsn = os.getenv("OPENCRAWL_TEST_DATASET_DSN")
    if not dsn:
        pytest.skip("Set OPENCRAWL_TEST_DATASET_DSN to an isolated PostgreSQL database.")
    schema = "oc_startup_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            scoped = make_conninfo(
                dsn, options=f"-c search_path={schema} -c statement_timeout=15000",
            )
            yield scoped
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_independent_cold_stores_initialize_concurrently(isolated_schema):
    # Each store has its own Python lock, as separate server instances do.
    # Exercise both initial table creation and existing-schema lock upgrades.
    for _ in range(2):
        stores = [ControlStore(isolated_schema) for _ in range(8)]
        start = threading.Barrier(len(stores))

        def initialize(store):
            start.wait(timeout=5)
            store.ensure_schema()
            return store._schema_ready

        with ThreadPoolExecutor(max_workers=len(stores)) as executor:
            futures = [executor.submit(initialize, store) for store in stores]
            assert all(future.result(timeout=30) for future in futures)
    with stores[0]._connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM ih_plans").fetchone()["n"] > 0
        assert connection.execute("SELECT count(*) AS n FROM ih_credit_packs").fetchone()["n"] > 0


def test_waiting_initializers_do_not_acquire_table_locks(isolated_schema):
    names = ["oc_init_" + uuid.uuid4().hex for _ in range(2)]
    stores = [ControlStore(make_conninfo(isolated_schema, application_name=name)) for name in names]
    with psycopg.connect(isolated_schema) as holder:
        holder.execute("SELECT pg_advisory_xact_lock(hashtext('opencrawl-control-schema'))")
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(store.ensure_schema) for store in stores]
            try:
                with psycopg.connect(isolated_schema, autocommit=True) as observer:
                    deadline = time.monotonic() + 5
                    waiting = 0
                    while time.monotonic() < deadline:
                        waiting = observer.execute(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE application_name = ANY(%s) AND wait_event = 'advisory'",
                            (names,),
                        ).fetchone()[0]
                        if waiting == 2 or all(future.done() for future in futures):
                            break
                        threading.Event().wait(0.02)
                    assert waiting == 2, "initializers must wait before acquiring schema table locks"
                    assert observer.execute("SELECT to_regclass('ih_users')").fetchone()[0] is None
            finally:
                holder.commit()
            for future in futures:
                future.result(timeout=30)
    assert all(store._schema_ready for store in stores)


def test_schema_failure_rolls_back_and_releases_startup_lock(isolated_schema, monkeypatch):
    store = ControlStore(isolated_schema)
    original = control_store.SCHEMA_SQL
    monkeypatch.setattr(control_store, "SCHEMA_SQL", original + "\nSELECT 1 / 0;")
    with pytest.raises(psycopg.errors.DivisionByZero):
        store.ensure_schema()
    assert not store._schema_ready
    with psycopg.connect(isolated_schema) as observer:
        assert observer.execute("SELECT to_regclass('ih_users')").fetchone()[0] is None
        assert observer.execute(
            "SELECT pg_try_advisory_xact_lock(hashtext('opencrawl-control-schema'))",
        ).fetchone()[0] is True
    monkeypatch.setattr(control_store, "SCHEMA_SQL", original)
    store.ensure_schema()
    assert store._schema_ready
