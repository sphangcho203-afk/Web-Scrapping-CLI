from __future__ import annotations

from pathlib import Path

from internet_hands.control_store import WALLET_UNITS_PER_USD


def test_internal_credit_denomination_is_exact() -> None:
    assert WALLET_UNITS_PER_USD == 5_000
    assert WALLET_UNITS_PER_USD % 100 == 0


def test_browser_sells_usage_credit_packs_and_uses_server_order_currency() -> None:
    source = Path("web/app.js").read_text(encoding="utf-8")
    assert 'id="custom-topup-form"' not in source
    assert "{amount_usd:" not in source
    assert "USAGE CREDIT PACKS" in source
    assert "Buy credits" in source
    assert "currency:r.order.currency||'INR'" in source
    assert "const walletMoney =" in source
    assert "$$('[data-buy]').forEach" in source
