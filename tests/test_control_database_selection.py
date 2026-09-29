from __future__ import annotations

import pytest

from internet_hands.control_migration import run_requested_control_plane_migration
from internet_hands.control_store import ControlStore


def test_control_store_defaults_to_control_plane_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNET_HANDS_CONTROL_POSTGRES_DSN", "postgresql://supabase/source")
    monkeypatch.setenv("INTERNET_HANDS_POSTGRES_DSN", "postgresql://neon/target")
    monkeypatch.delenv("OPENCRAWL_PRIMARY_DATABASE", raising=False)

    assert ControlStore().dsn == "postgresql://supabase/source"


def test_control_store_can_cut_over_to_neon_without_secret_rebinding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTERNET_HANDS_CONTROL_POSTGRES_DSN", "postgresql://supabase/source")
    monkeypatch.setenv("INTERNET_HANDS_POSTGRES_DSN", "postgresql://neon/target")
    monkeypatch.setenv("OPENCRAWL_PRIMARY_DATABASE", "neon")

    assert ControlStore().dsn == "postgresql://neon/target"


def test_control_migration_is_disabled_without_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCRAWL_CONTROL_MIGRATION_ID", raising=False)

    assert run_requested_control_plane_migration() is None


def test_control_migration_requires_both_source_and_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCRAWL_CONTROL_MIGRATION_ID", "test-cutover")
    monkeypatch.delenv("INTERNET_HANDS_CONTROL_POSTGRES_DSN", raising=False)
    monkeypatch.setenv("INTERNET_HANDS_POSTGRES_DSN", "postgresql://neon/target")

    with pytest.raises(RuntimeError, match="requires both"):
        run_requested_control_plane_migration()



def test_control_database_connection_timeout_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = {}

    def fake_connect(dsn, **kwargs):
        seen["dsn"] = dsn
        seen["kwargs"] = kwargs
        return object()

    monkeypatch.setenv("OPENCRAWL_DB_CONNECT_TIMEOUT_SECONDS", "999")
    monkeypatch.setattr("internet_hands.control_store.psycopg.connect", fake_connect)

    result = ControlStore("postgresql://db.example/open_crawl")._connect()

    assert result is not None
    assert seen["dsn"] == "postgresql://db.example/open_crawl"
    assert seen["kwargs"]["connect_timeout"] == 30
