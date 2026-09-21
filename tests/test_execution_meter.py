from __future__ import annotations

import asyncio

import pytest

from internet_hands.execution_meter import (
    execution_usage_snapshot,
    record_provider_call,
    record_usage,
    reset_execution_meter,
    start_execution_meter,
)


def test_execution_meter_records_and_resets() -> None:
    token = start_execution_meter()
    try:
        record_usage("pages", 3)
        record_provider_call("twilio")
        assert execution_usage_snapshot() == {
            "counters": {"pages": 3},
            "provider_calls": {"twilio": 1},
        }
    finally:
        reset_execution_meter(token)

    assert execution_usage_snapshot() == {
        "counters": {},
        "provider_calls": {},
    }


@pytest.mark.asyncio
async def test_execution_meter_is_shared_by_child_tasks() -> None:
    token = start_execution_meter()

    async def child(provider: str) -> None:
        await asyncio.sleep(0)
        record_usage("items")
        record_provider_call(provider)

    try:
        await asyncio.gather(child("veriphone"), child("abstract"))
        snapshot = execution_usage_snapshot()
        assert snapshot["counters"]["items"] == 2
        assert snapshot["provider_calls"] == {
            "abstract": 1,
            "veriphone": 1,
        }
    finally:
        reset_execution_meter(token)
