from __future__ import annotations

from internet_hands import rewards


def test_default_reward_rate_is_raw_work_not_current_wallet_burn(monkeypatch) -> None:
    monkeypatch.delenv("OPENCRAWL_REWARD_UNITS_PER_POINT", raising=False)
    monkeypatch.delenv("OPENCRAWL_CREDIT_BURN_MULTIPLIER", raising=False)

    assert rewards._reward_units_per_point() == 250
    assert rewards._points_from_usage(249) == 0
    assert rewards._points_from_usage(250) == 1
    assert rewards._points_from_usage(25_000) == 100

    # Changing today's wallet pricing policy must not reprice reward work.
    monkeypatch.setenv("OPENCRAWL_CREDIT_BURN_MULTIPLIER", "9")
    assert rewards._reward_units_per_point() == 250


def test_reward_catalog_wallet_values_match_display_currency() -> None:
    rows = {row[0]: row for row in rewards.REWARD_ROWS}
    assert rows["wallet-025"][5] == 1_250
    assert rows["wallet-100"][5] == 5_000
    assert rows["wallet-500"][5] == 25_000
    assert rewards.WALLET_UNITS_PER_USD == 5_000



def test_accrual_uses_only_unprocessed_metered_units() -> None:
    # Existing processed spend is never re-priced when the earning rate changes.
    points, consumed = rewards._accrual_delta(50_000, 25_000, 500)
    assert points == 50
    assert consumed == 25_000

    # Incomplete spend remains available for the next accrual instead of being discarded.
    points, consumed = rewards._accrual_delta(25_499, 25_000, 500)
    assert points == 0
    assert consumed == 0
    points, consumed = rewards._accrual_delta(25_500, 25_000, 500)
    assert points == 1
    assert consumed == 500



def test_reward_code_normalization_and_hashing(monkeypatch) -> None:
    monkeypatch.setenv("OPENCRAWL_REWARD_CODE_SECRET", "fixture-secret-key-123456789")
    assert rewards._normalize_reward_code(" discord-100 ") == "DISCORD-100"
    first = rewards._reward_code_hash("discord-100")
    second = rewards._reward_code_hash("DISCORD-100")
    assert first == second
    assert len(first) == 64
    assert "DISCORD-100" not in first
