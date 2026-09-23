import pytest

from internet_hands.revenue_ops import calculate_unit_economics, score_lead


def test_high_fit_lead_qualifies() -> None:
    result = score_lead(
        {
            "recurring_monitoring_burden": 1,
            "agency_or_client_leverage": 1,
            "observable_competitive_research_signal": 1,
            "reachable_decision_maker": 0.5,
            "budget_proxy": 0,
        }
    )

    assert result.score == 83
    assert result.qualified is True


def test_low_fit_lead_does_not_qualify() -> None:
    result = score_lead(
        {
            "recurring_monitoring_burden": 0.5,
            "agency_or_client_leverage": 0,
            "observable_competitive_research_signal": 0.5,
            "reachable_decision_maker": 0,
            "budget_proxy": 0,
        }
    )

    assert result.score == 25
    assert result.qualified is False


def test_lead_signal_out_of_range_is_rejected() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        score_lead({"recurring_monitoring_burden": 1.1})


def test_unit_economics_passes_80_percent_floor() -> None:
    result = calculate_unit_economics(revenue=500, direct_cost=90)

    assert result.gross_profit == 410
    assert result.gross_margin_pct == 82
    assert result.passes_margin_floor is True


def test_unit_economics_rejects_nonpositive_revenue() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        calculate_unit_economics(revenue=0, direct_cost=0)
