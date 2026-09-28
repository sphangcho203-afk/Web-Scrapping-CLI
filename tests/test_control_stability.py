from __future__ import annotations

from typing import Any

import pytest

from internet_hands.control_store import (
    PLAN_ROWS,
    SCHEMA_SQL,
    AuthIdentity,
    ControlError,
    ControlStore,
)


class _Cursor:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.executed: list[str] = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql: str, params=()) -> None:
        del params
        self.executed.append(" ".join(sql.split()).lower())

    def fetchone(self):
        if not self.responses:
            raise AssertionError("unexpected fetchone")
        return self.responses.pop(0)

    def fetchall(self):
        return []


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self._cursor

    def commit(self) -> None:
        self.commits += 1


class _Store(ControlStore):
    def __init__(self, cursor: _Cursor) -> None:
        super().__init__("postgresql://example/open_crawl")
        self.cursor = cursor
        self.connection = _Connection(cursor)

    def ensure_schema(self) -> None:
        return None

    def _connect(self):
        return self.connection


def test_api_key_creation_has_no_per_plan_count_limit() -> None:
    assert all(row[6] is None for row in PLAN_ROWS)
    concurrency = [row[5] for row in PLAN_ROWS]
    assert concurrency[0] >= 2
    assert concurrency == sorted(concurrency)
    assert "ALTER TABLE ih_plans ALTER COLUMN api_key_limit DROP NOT NULL" in SCHEMA_SQL
    cursor = _Cursor([
        {"id": f"key_{index}", "name": f"key {index}"}
        for index in range(25)
    ])
    store = _Store(cursor)
    for index in range(25):
        key = store.create_api_key(
            user_id="usr_1", name=f"key {index}", prefix=f"ih_{index}",
            key_hash=f"hash_{index}", scopes=["mcp:read"], environment="live",
        )
        assert key["name"] == f"key {index}"
    assert len(cursor.executed) == 25
    assert all(query.startswith("insert into ih_api_keys") for query in cursor.executed)
    assert store.connection.commits == 25


def test_terminal_settlement_is_idempotent_and_immutable() -> None:
    cursor = _Cursor(
        [
            {
                "user_id": "usr_1",
                "status": "abandoned",
                "credits_charged": 0,
                "metadata": {
                    "reservation": {
                        "state": "abandoned",
                        "reserved": 50,
                        "settled": 0,
                        "released": 50,
                    }
                },
            }
        ]
    )
    store = _Store(cursor)

    charged = store.settle_tool_call(
        "req_1",
        status="ok",
        latency_ms=999,
        output_bytes=123,
        actual_credits=50,
        execution_usage={
            "provider_events": [
                {
                    "provider": "firecrawl",
                    "ref": "firecrawl:search",
                    "status": "completed",
                    "attempt": 1,
                }
            ]
        },
    )

    assert charged == 0
    assert len(cursor.executed) == 1
    assert cursor.executed[0].startswith(
        "select user_id,status,credits_charged,metadata"
    )
    assert store.connection.commits == 0


class _ConcurrencyStore(_Store):
    def release_stale_reservations(self, user_id: str, **kwargs):
        del user_id, kwargs
        return {"reservations_released": 0, "credits_released": 0}

    def quote_tool_call(self, **kwargs):
        del kwargs
        return {
            "credits": 10,
            "category": "provider",
            "provider_class": "public",
            "minimum_plan": "free",
            "breakdown": [],
        }


def test_reservation_rejects_plan_concurrency_before_execution() -> None:
    cursor = _Cursor(
        [
            {"n": 0},
            {
                "monthly_credits": 1000,
                "purchased_credits": 0,
                "reserved_credits": 20,
            },
            {"n": 2},
        ]
    )
    store = _ConcurrencyStore(cursor)
    identity = AuthIdentity(
        user_id="usr_1",
        api_key_id="key_1",
        scopes=["mcp:execute"],
        plan_slug="builder",
        rpm_limit=60,
        source="api_key",
        concurrent_limit=2,
    )

    with pytest.raises(ControlError) as caught:
        store.reserve_tool_call(
            identity=identity,
            request_id="req_2",
            tool_name="mesh_execute",
            arguments={"ref": "nativeweb:search", "arguments": {"query": "x"}},
            input_bytes=10,
        )

    assert caught.value.code == "concurrency_limited"
    assert caught.value.status_code == 429
    assert store.connection.commits == 0
    assert not any(sql.startswith("insert into ih_usage_events") for sql in cursor.executed)
