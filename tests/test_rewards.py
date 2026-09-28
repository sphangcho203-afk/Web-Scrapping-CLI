from __future__ import annotations

from internet_hands import rewards


def test_default_reward_rate_is_five_cents_per_point(monkeypatch) -> None:
    monkeypatch.delenv("OPENCRAWL_REWARD_UNITS_PER_POINT", raising=False)
    assert rewards._reward_units_per_point() == 250
    assert rewards._points_from_usage(249) == 0
    assert rewards._points_from_usage(250) == 1
    assert rewards._points_from_usage(25_000) == 100


def test_reward_catalog_wallet_values_match_display_currency() -> None:
    rows = {row[0]: row for row in rewards.REWARD_ROWS}
    assert rows["wallet-025"][5] == 1_250
    assert rows["wallet-100"][5] == 5_000
    assert rows["wallet-500"][5] == 25_000
    assert rewards.WALLET_UNITS_PER_USD == 5_000
