from __future__ import annotations

import asyncio

import pytest

from internet_hands.mcp_verify import MemoryStorage, verify, verify_receipt


def test_execution_requires_a_total_spending_limit_before_authentication():
    with pytest.raises(ValueError, match="max-total-credits"):
        asyncio.run(verify(execute=True))


def test_receipt_can_split_monthly_and_purchased_but_cannot_double_charge_a_bucket():
    monthly = {"reference_id": "req_test", "kind": "usage", "bucket": "monthly", "amount": -20,
        "metadata": {"reservation": {"settled": 36}}}
    purchased = {**monthly, "bucket": "purchased", "amount": -16}
    assert verify_receipt({"ledger": [monthly, purchased]}, "req_test", 36) == 36
    with pytest.raises(RuntimeError, match="duplicated"):
        verify_receipt({"ledger": [monthly, monthly]}, "req_test", 36)
    with pytest.raises(RuntimeError, match="missing"):
        verify_receipt({"ledger": [monthly]}, "req_other", 36)
    with pytest.raises(RuntimeError, match="cap"):
        verify_receipt({"ledger": [monthly, purchased]}, "req_test", 35)
    with pytest.raises(RuntimeError, match="disagree"):
        verify_receipt({"ledger": [{**monthly, "amount": -19}]}, "req_test", 36)


@pytest.mark.asyncio
async def test_token_storage_is_process_local():
    one, two = MemoryStorage(), MemoryStorage()
    await one.set_tokens("in-memory-only")
    await one.set_client_info("client")
    assert await one.get_tokens() == "in-memory-only"
    assert await one.get_client_info() == "client"
    assert await two.get_tokens() is None
