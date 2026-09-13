from __future__ import annotations

import pytest
from fastapi import HTTPException

from internet_hands.control_hardening import _validate_payment_against_order


def _order() -> dict[str, object]:
    return {"order_id": "order_123", "amount_paise": 49900, "currency": "INR"}


def test_captured_payment_matches_order() -> None:
    _validate_payment_against_order(
        {
            "id": "pay_123",
            "status": "captured",
            "order_id": "order_123",
            "amount": 49900,
            "currency": "INR",
        },
        _order(),
    )


@pytest.mark.parametrize("status", ["created", "authorized", "failed", "refunded"])
def test_non_captured_payment_is_rejected(status: str) -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_payment_against_order(
            {
                "id": "pay_123",
                "status": status,
                "order_id": "order_123",
                "amount": 49900,
                "currency": "INR",
            },
            _order(),
        )
    assert exc.value.status_code == 409


def test_mismatched_order_is_rejected() -> None:
    with pytest.raises(HTTPException, match="order"):
        _validate_payment_against_order(
            {
                "id": "pay_123",
                "status": "captured",
                "order_id": "order_other",
                "amount": 49900,
                "currency": "INR",
            },
            _order(),
        )


def test_mismatched_amount_is_rejected() -> None:
    with pytest.raises(HTTPException, match="amount"):
        _validate_payment_against_order(
            {
                "id": "pay_123",
                "status": "captured",
                "order_id": "order_123",
                "amount": 1,
                "currency": "INR",
            },
            _order(),
        )
