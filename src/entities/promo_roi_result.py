"""Promo ROI result entity — per-quantile profit projections."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PromoROIResult:
    """Gross and net profit per quantile for a promo simulation.

    Produced by the profit calculation step within SimulatePromoROIService.
    Consumed by ComputeDecisionUncertaintyService for Monte Carlo aggregation.

    When cogs_source == 'scenario_default', result is an approximation.
    uses_default_cogs=True triggers Risk Note in RecommendationObject:
    'Warning: Using default margin assumption. ROI is a rough estimate.'

    Net ROI = (gross_profit - execution_cost) / baseline_revenue × 100.
    """
    item_id           : str
    store_id          : str
    cogs_pct          : float
    cogs_source       : str       # "item_specific" | "scenario_default"
    scenario_used     : str | None  # "NORMAL_MARGIN" etc if fallback
    promo_fixed_cost  : float
    baseline_revenue  : float
    # Per-quantile revenue projections
    promo_revenue_q40 : float
    promo_revenue_q60 : float
    promo_revenue_q80 : float
    # Per-quantile gross profit (revenue × margin - promo_cost)
    gross_profit_q40  : float
    gross_profit_q60  : float
    gross_profit_q80  : float
    # Per-quantile net ROI %
    net_roi_pct_q40   : float
    net_roi_pct_q60   : float
    net_roi_pct_q80   : float
    breakeven_uplift_pct: float
    is_profitable_q50 : bool      # net_roi_pct_q60 > 0

    @property
    def uses_default_cogs(self) -> bool:
        return self.cogs_source == "scenario_default"

    def roi_range(self) -> tuple[float, float]:
        """(q40 ROI, q80 ROI) as confidence interval."""
        return (self.net_roi_pct_q40, self.net_roi_pct_q80)

    def risk_note(self) -> str | None:
        if self.uses_default_cogs:
            return (
                f"Using default margin assumption ({self.scenario_used}). "
                "ROI is a rough estimate. Update COGS in item_financial_assumptions."
            )
        return None
