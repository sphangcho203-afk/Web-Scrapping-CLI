from __future__ import annotations

import json
import logging
import os
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .control_store import ControlStore
from .security_store import SecurityStore

logger = logging.getLogger(__name__)
MIGRATION_TABLE = "ih_control_migrations"


def _connect(dsn: str):
    options: dict[str, Any] = {"row_factory": dict_row}
    if "pooler.supabase.com" in dsn:
        options["prepare_threshold"] = None
    return psycopg.connect(dsn, **options)


def _table_names(conn: Any) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT tablename
            FROM pg_catalog.pg_tables
            WHERE schemaname='public' AND tablename LIKE 'ih\\_%' ESCAPE '\\'
            ORDER BY tablename
            """
        )
        return [str(row["tablename"]) for row in cur.fetchall()]


def _columns(conn: Any, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        return [str(row["column_name"]) for row in cur.fetchall()]


def _dependency_order(conn: Any, tables: set[str]) -> list[str]:
    dependencies: dict[str, set[str]] = {table: set() for table in tables}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT child.relname AS child_table, parent.relname AS parent_table
            FROM pg_constraint c
            JOIN pg_class child ON child.oid=c.conrelid
            JOIN pg_class parent ON parent.oid=c.confrelid
            JOIN pg_namespace n ON n.oid=child.relnamespace
            WHERE c.contype='f' AND n.nspname='public'
            """
        )
        for row in cur.fetchall():
            child = str(row["child_table"])
            parent = str(row["parent_table"])
            if child in tables and parent in tables and child != parent:
                dependencies[child].add(parent)

    ordered: list[str] = []
    resolved: set[str] = set()
    remaining = set(tables)
    while remaining:
        ready = sorted(table for table in remaining if dependencies[table] <= resolved)
        if not ready:
            blocked = {table: sorted(dependencies[table] - resolved) for table in sorted(remaining)}
            raise RuntimeError(f"control-plane foreign-key dependency cycle: {blocked}")
        ordered.extend(ready)
        resolved.update(ready)
        remaining.difference_update(ready)
    return ordered


def _copy_table(source: Any, target: Any, table: str, columns: list[str]) -> int:
    identifiers = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    source_query = sql.SQL("COPY (SELECT {} FROM {}) TO STDOUT").format(
        identifiers,
        sql.Identifier(table),
    )
    target_query = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table),
        identifiers,
    )

    with (
        source.cursor() as source_cur,
        target.cursor() as target_cur,
        source_cur.copy(source_query) as copy_out,
        target_cur.copy(target_query) as copy_in,
    ):
        for chunk in copy_out:
            copy_in.write(chunk)

    with source.cursor() as cur:
        cur.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(table)))
        return int(cur.fetchone()["n"])


def _backfill_supabase_identities(source: Any, target: Any) -> int:
    with source.cursor() as cur:
        cur.execute("SELECT to_regclass('public.profiles') IS NOT NULL AS exists")
        if not bool(cur.fetchone()["exists"]):
            return 0
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='public' AND table_name='profiles'
                  AND column_name='legacy_user_id'
            ) AS has_legacy
            """
        )
        has_legacy = bool(cur.fetchone()["has_legacy"])
        if has_legacy:
            cur.execute(
                """
                SELECT id::text AS auth_subject, legacy_user_id::text AS legacy_user_id
                FROM profiles
                """
            )
        else:
            cur.execute(
                "SELECT id::text AS auth_subject, NULL::text AS legacy_user_id FROM profiles"
            )
        mappings = cur.fetchall()

    updated = 0
    with target.cursor() as cur:
        for row in mappings:
            auth_subject = str(row["auth_subject"])
            legacy_user_id = str(row["legacy_user_id"]) if row.get("legacy_user_id") else None
            cur.execute(
                """
                UPDATE ih_users
                SET auth_provider='supabase',auth_subject=%s,updated_at=now()
                WHERE (id=%s OR id=%s)
                  AND (
                    auth_subject IS NULL
                    OR (auth_provider='supabase' AND auth_subject=%s)
                  )
                """,
                (auth_subject, legacy_user_id, auth_subject, auth_subject),
            )
            updated += int(cur.rowcount)
    return updated


def _ensure_migration_table(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} (
                migration_id text PRIMARY KEY,
                source_table_counts jsonb NOT NULL,
                target_table_counts jsonb NOT NULL,
                identity_links integer NOT NULL DEFAULT 0,
                completed_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
    conn.commit()


def _already_completed(conn: Any, migration_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT * FROM {MIGRATION_TABLE} WHERE migration_id=%s",
            (migration_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def migrate_control_plane(*, migration_id: str, source_dsn: str, target_dsn: str) -> dict[str, Any]:
    if not migration_id:
        raise RuntimeError("migration id is required")
    if source_dsn == target_dsn:
        return {"migration_id": migration_id, "skipped": True, "reason": "same_database"}

    target_store = ControlStore(target_dsn)
    target_store.ensure_schema()
    SecurityStore(target_store).ensure_schema()

    with _connect(target_dsn) as target:
        _ensure_migration_table(target)
        completed = _already_completed(target, migration_id)
        if completed:
            return {
                "migration_id": migration_id,
                "skipped": True,
                "reason": "already_completed",
                "completed_at": completed.get("completed_at"),
            }

    with _connect(source_dsn) as source, _connect(target_dsn) as target:
        source.autocommit = False
        target.autocommit = False
        try:
            with source.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            with target.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('opencrawl-control-plane-migration'))"
                )

            completed = _already_completed(target, migration_id)
            if completed:
                target.rollback()
                source.rollback()
                return {
                    "migration_id": migration_id,
                    "skipped": True,
                    "reason": "already_completed",
                }

            source_tables = set(_table_names(source))
            target_tables = set(_table_names(target))
            tables = sorted(
                (source_tables & target_tables) - {MIGRATION_TABLE}
            )
            if "ih_users" not in tables:
                raise RuntimeError("source control plane is missing ih_users")

            order = _dependency_order(source, set(tables))
            source_counts: dict[str, int] = {}
            target_counts: dict[str, int] = {}

            with target.cursor() as cur:
                cur.execute(
                    sql.SQL("TRUNCATE TABLE {} CASCADE").format(
                        sql.SQL(", ").join(sql.Identifier(table) for table in tables)
                    )
                )

            for table in order:
                source_columns = _columns(source, table)
                target_columns = set(_columns(target, table))
                columns = [column for column in source_columns if column in target_columns]
                if not columns:
                    raise RuntimeError(f"no compatible columns for {table}")
                source_counts[table] = _copy_table(source, target, table, columns)

            identity_links = _backfill_supabase_identities(source, target)

            with target.cursor() as cur:
                for table in order:
                    cur.execute(
                        sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(table))
                    )
                    target_counts[table] = int(cur.fetchone()["n"])

            mismatches = {
                table: {"source": source_counts[table], "target": target_counts[table]}
                for table in order
                if source_counts[table] != target_counts[table]
            }
            if mismatches:
                raise RuntimeError(f"control-plane row-count mismatch: {mismatches}")

            with target.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {MIGRATION_TABLE}(
                        migration_id,source_table_counts,target_table_counts,identity_links
                    ) VALUES (%s,%s::jsonb,%s::jsonb,%s)
                    """,
                    (
                        migration_id,
                        json.dumps(source_counts, sort_keys=True),
                        json.dumps(target_counts, sort_keys=True),
                        identity_links,
                    ),
                )
            target.commit()
            source.rollback()
            logger.info(
                "control-plane migration completed",
                extra={
                    "migration_id": migration_id,
                    "tables": len(order),
                    "identity_links": identity_links,
                },
            )
            return {
                "migration_id": migration_id,
                "skipped": False,
                "tables": len(order),
                "rows": sum(source_counts.values()),
                "identity_links": identity_links,
                "verified": True,
            }
        except Exception:
            target.rollback()
            source.rollback()
            logger.exception("control-plane migration failed", extra={"migration_id": migration_id})
            raise


def run_requested_control_plane_migration() -> dict[str, Any] | None:
    migration_id = (os.getenv("OPENCRAWL_CONTROL_MIGRATION_ID") or "").strip()
    if not migration_id:
        return None
    source_dsn = os.getenv("INTERNET_HANDS_CONTROL_POSTGRES_DSN") or ""
    target_dsn = os.getenv("INTERNET_HANDS_POSTGRES_DSN") or ""
    if not source_dsn or not target_dsn:
        raise RuntimeError(
            "control-plane migration requires both INTERNET_HANDS_CONTROL_POSTGRES_DSN "
            "and INTERNET_HANDS_POSTGRES_DSN"
        )
    return migrate_control_plane(
        migration_id=migration_id,
        source_dsn=source_dsn,
        target_dsn=target_dsn,
    )
