from __future__ import annotations

from pathlib import Path

import pytest

from internet_hands.control_api import _parse_custom_topup_cents
from internet_hands.control_store import (
    CUSTOM_TOPUP_MAX_USD_CENTS,
    CUSTOM_TOPUP_MIN_USD_CENTS,
    WALLET_UNITS_PER_USD,
    ControlError,
)


def test_wallet_denomination_is_exact_at_cent_precision() -> None:
    assert WALLET_UNITS_PER_USD == 5_000
    assert WALLET_UNITS_PER_USD % 100 == 0
    assert 100 * WALLET_UNITS_PER_USD // 100 == 5_000
    assert 1 * WALLET_UNITS_PER_USD // 100 == 50


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", 100),
        ("10.00", 1_000),
        ("12.34", 1_234),
        (500, 50_000),
    ],
)
def test_custom_topup_parser_accepts_valid_usd_amounts(value: object, expected: int) -> None:
    assert _parse_custom_topup_cents(value) == expected


@pytest.mark.parametrize("value", [None, "", "0", "-1", "1.001", "500.01", "NaN", "Infinity"])
def test_custom_topup_parser_rejects_invalid_amounts(value: object) -> None:
    with pytest.raises(ControlError):
        _parse_custom_topup_cents(value)


def test_custom_topup_bounds_are_explicit() -> None:
    assert CUSTOM_TOPUP_MIN_USD_CENTS == 100
    assert CUSTOM_TOPUP_MAX_USD_CENTS == 50_000


def test_browser_sells_usage_credit_packs_and_uses_server_order_currency() -> None:
    source = Path("web/app.js").read_text(encoding="utf-8")
    assert 'id="custom-topup-form"' not in source
    assert "USAGE CREDIT PACKS" in source
    assert "Buy credits" in source
    assert "currency:r.order.currency||'INR'" in source
    assert "const walletMoney =" in source
    assert "$('[data-buy]').forEach" in source
