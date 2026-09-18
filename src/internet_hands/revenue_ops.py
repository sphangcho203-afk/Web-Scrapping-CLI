from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

LEAD_WEIGHTS = {
    "recurring_monitoring_burden": 30,
    "agency_or_client_leverage": 25,
    "observable_competitive_research_signal": 20,
    "reachable_decision_maker": 15,
    "budget_proxy": 10,
}
QUALIFIED_THRESHOLD = 70
DEFAULT_MARGIN_FLOOR_PCT = 80.0


@dataclass(frozen=True)
class LeadScore:
    score: int
    qualified: bool
    components: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class UnitEconomics:
    revenue: float
    direct_cost: float
    gross_profit: float
    gross_margin_pct: float
    passes_margin_floor: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def score_lead(signals: Mapping[str, float | int | bool]) -> LeadScore:
    components: dict[str, int] = {}
    for key, weight in LEAD_WEIGHTS.items():
        raw = signals.get(key, 0)
        normalized = 1.0 if raw is True else 0.0 if raw is False else float(raw)
        if not 0.0 <= normalized <= 1.0:
            raise ValueError(f"{key} must be between 0 and 1")
        components[key] = round(weight * normalized)

    score = sum(components.values())
    return LeadScore(
        score=score,
        qualified=score >= QUALIFIED_THRESHOLD,
        components=components,
    )


def calculate_unit_economics(
    revenue: float,
    direct_cost: float,
    margin_floor_pct: float = DEFAULT_MARGIN_FLOOR_PCT,
) -> UnitEconomics:
    if revenue <= 0:
        raise ValueError("revenue must be greater than zero")
    if direct_cost < 0:
        raise ValueError("direct_cost cannot be negative")
    if not 0 <= margin_floor_pct <= 100:
        raise ValueError("margin_floor_pct must be between 0 and 100")

    gross_profit = revenue - direct_cost
    gross_margin_pct = (gross_profit / revenue) * 100.0
    return UnitEconomics(
        revenue=round(revenue, 2),
        direct_cost=round(direct_cost, 2),
        gross_profit=round(gross_profit, 2),
        gross_margin_pct=round(gross_margin_pct, 2),
        passes_margin_floor=gross_margin_pct >= margin_floor_pct,
    )
