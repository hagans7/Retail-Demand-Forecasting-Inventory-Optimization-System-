"""Compute revenue analytics service — unit vs revenue divergence analysis."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from src.core.constants.analytics_constants import (
    BASELINE_PROMO_REVENUE_UPLIFT_PCT,
    BASELINE_UNIT_VS_REVENUE_DIVERGENCE,
    PROMO_BREAKEVEN_UPLIFT_PCT,
)
from src.core.logging.logger import get_logger
from src.entities.revenue_metric import DailyRevenueMetric, RevenueAnalyticsSummary
from src.interfaces.base_analytics_repository import BaseAnalyticsRepository


class ComputeRevenueAnalyticsService:
    """Computes revenue analytics for the /analytics/revenue endpoint.

    Primary insight: promo drives units +50% but revenue only +20% due to discount.
    Divergence = unit_uplift_pct - revenue_uplift_pct (validated at 30.04pp in R&D).
    """

    def __init__(self, analytics_repo: BaseAnalyticsRepository) -> None:
        self._analytics = analytics_repo
        self._logger    = get_logger(__name__)

    async def execute(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> RevenueAnalyticsSummary:
        today     = date.today()
        end_date  = end_date   or today
        start_date= start_date or (today - timedelta(days=28))

        df = await self._analytics.get_revenue_for_period(start_date, end_date)
        if df.empty:
            self._logger.warning("Revenue analytics: no data found",
                                 extra={"operation": "compute_revenue_analytics"})
            return RevenueAnalyticsSummary(
                period_start=start_date, period_end=end_date,
                total_revenue_baseline=0.0, total_revenue_promo_on=0.0,
                revenue_uplift_pct=0.0, unit_uplift_pct=0.0,
                unit_vs_revenue_divergence_pp=0.0,
            )

        promo_df    = df[df["promo"] == 1]
        nopromo_df  = df[df["promo"] == 0]

        avg_rev_promo  = float(promo_df["revenue"].mean())   if not promo_df.empty   else 0.0
        avg_rev_normal = float(nopromo_df["revenue"].mean()) if not nopromo_df.empty else 0.0
        avg_sal_promo  = float(promo_df["sales"].mean())     if "sales" in promo_df.columns  and not promo_df.empty  else 0.0
        avg_sal_normal = float(nopromo_df["sales"].mean())   if "sales" in nopromo_df.columns and not nopromo_df.empty else 0.0

        rev_uplift  = (avg_rev_promo  - avg_rev_normal)  / max(avg_rev_normal,  0.01) * 100
        unit_uplift = (avg_sal_promo  - avg_sal_normal)  / max(avg_sal_normal,  0.01) * 100
        divergence  = unit_uplift - rev_uplift

        # Pareto: top items by revenue
        if "item_id" in df.columns:
            top_items = (df.groupby("item_id")["revenue"].sum()
                         .sort_values(ascending=False)
                         .head(10)
                         .reset_index()
                         .rename(columns={"revenue": "total_revenue"})
                         .to_dict("records"))
        else:
            top_items = []

        self._logger.info(
            "Revenue analytics computed",
            extra={"rev_uplift_pct": round(rev_uplift, 2),
                   "unit_uplift_pct": round(unit_uplift, 2),
                   "divergence_pp": round(divergence, 2),
                   "operation": "compute_revenue_analytics"},
        )
        return RevenueAnalyticsSummary(
            period_start=start_date, period_end=end_date,
            total_revenue_baseline=round(avg_rev_normal * len(nopromo_df), 2),
            total_revenue_promo_on=round(avg_rev_promo  * len(promo_df),   2),
            revenue_uplift_pct=round(rev_uplift,  2),
            unit_uplift_pct=round(unit_uplift, 2),
            unit_vs_revenue_divergence_pp=round(divergence, 2),
            top_items_by_revenue=top_items,
        )
