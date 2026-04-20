"""Promo simulation entity."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PromoSimulationResult:
    """Basic promo simulation output (V1 compatible).

    Enhanced version (V2) is PromoROIResult + RecommendationObject.
    This entity remains for backward compatibility with /simulate-promo/ endpoint.
    """
    store_id               : str
    item_id                : str
    baseline_forecast      : float
    promo_forecast         : float
    expected_uplift_units  : float
    expected_uplift_pct    : float
    revenue_uplift_pct     : float
    additional_stock_needed: int
    confidence             : str = "HIGH"
    simulation_id          : str = ""

    def is_worth_promoting(self, min_uplift_pct: float = 20.0) -> bool:
        return self.expected_uplift_pct >= min_uplift_pct

    def unit_vs_revenue_divergence(self) -> float:
        """Positive = volume up but revenue diluted by discount."""
        return self.expected_uplift_pct - self.revenue_uplift_pct
