"""Revenue metric entities."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class DailyRevenueMetric:
    """Per-row revenue metric. revenue = sales × price."""
    date            : date
    store_id        : str
    item_id         : str
    predicted_units : float
    price           : float
    predicted_revenue: float
    promo_flag      : int


@dataclass
class RevenueAnalyticsSummary:
    """Aggregate revenue analytics over a period.

    unit_vs_revenue_divergence > 0 means volume gained but revenue diluted
    by discount — the core insight from analytics_validation notebook.
    """
    period_start           : date
    period_end             : date
    total_revenue_baseline : float
    total_revenue_promo_on : float
    revenue_uplift_pct     : float
    unit_uplift_pct        : float
    unit_vs_revenue_divergence_pp: float    # unit_uplift - revenue_uplift
    top_items_by_revenue   : list[dict] = field(default_factory=list)

    def is_promo_revenue_positive(self) -> bool:
        return self.revenue_uplift_pct > 0
