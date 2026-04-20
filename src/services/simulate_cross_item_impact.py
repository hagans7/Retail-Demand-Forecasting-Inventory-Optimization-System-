"""Simulate cross-item impact — cannibalization and halo effect.

Algorithm:
    1. Load correlation matrix from analytics_repository
    2. Extract row for source item
    3. Classify: SUBSTITUTE (corr < -0.20), COMPLEMENTARY (corr > 0.50), INDEPENDENT
    4. Estimate loss for substitutes: avg_sales × |corr| × discount_rate × 0.5
    5. Estimate gain for complements: avg_sales × corr × uplift_pct × 0.3
    6. Aggregate basket impact; compute cannibalization_penalty_pct

Dampening factors: substitution=0.5, halo=0.3 (conservative; correlation ≠ causation).
Known limitation documented in Section 19 of blueprint.
"""
from __future__ import annotations

from src.core.constants.decision_constants import (
    CANNIBALIZATION_DAMPENING,
    COMPLEMENTARY_CORRELATION_THRESHOLD,
    HALO_DAMPENING,
    SUBSTITUTE_CORRELATION_THRESHOLD,
)
from src.core.logging.logger import get_logger
from src.entities.cross_item_impact import CrossItemImpact, ItemRelationship


class SimulateCrossItemImpactService:
    """Estimates basket revenue impact when promo activates on source item.

    Correlation matrix precomputed weekly by analytics_snapshot_pipeline
    and cached. Each cell = sales correlation between two items (non-promo
    days only to avoid promo confounding).
    """

    def __init__(self) -> None:
        self._logger = get_logger(__name__)

    async def execute(
        self,
        store_id: str,
        source_item: str,
        discount_rate: float,
        uplift_pct: float,
        correlation_matrix: dict[str, dict[str, float]] | None = None,
        avg_daily_sales: dict[str, float] | None = None,
    ) -> CrossItemImpact:
        """Estimate cross-item basket impact.

        Args:
            correlation_matrix: {item_id: {other_item_id: correlation}}.
                                 None → returns zero-impact (graceful degrade).
            avg_daily_sales:    {item_id: avg_daily_sales} for monetization.
        """
        if correlation_matrix is None or source_item not in correlation_matrix:
            self._logger.warning(
                "Correlation matrix unavailable — returning zero cross-item impact",
                extra={"store_id": store_id, "source_item": source_item,
                       "operation": "simulate_cross_item_impact"},
            )
            return CrossItemImpact(source_item=source_item)

        item_correlations = correlation_matrix[source_item]
        avg_sales = avg_daily_sales or {}
        baseline_revenue_all = sum(avg_sales.values()) * 7  # 7-day basket

        impacted_items  = []
        substitution_loss_abs = 0.0
        halo_gain_abs         = 0.0

        for other_item, corr in item_correlations.items():
            if other_item == source_item:
                continue

            relationship = self._classify(corr)
            if relationship == ItemRelationship.INDEPENDENT:
                continue

            other_avg = avg_sales.get(other_item, 0.0) * 7  # 7-day baseline

            if relationship == ItemRelationship.SUBSTITUTE:
                impact_abs = other_avg * abs(corr) * discount_rate * CANNIBALIZATION_DAMPENING
                impact_pct = -impact_abs / max(other_avg, 1) * 100
                substitution_loss_abs += impact_abs
            else:  # COMPLEMENTARY
                impact_abs = other_avg * corr * (uplift_pct / 100) * HALO_DAMPENING
                impact_pct = impact_abs / max(other_avg, 1) * 100
                halo_gain_abs += impact_abs

            impacted_items.append({
                "item_id":      other_item,
                "relationship": relationship.value,
                "correlation":  round(corr, 3),
                "impact_pct":   round(impact_pct, 2),
            })

        if baseline_revenue_all > 0:
            substitution_loss_pct = substitution_loss_abs / baseline_revenue_all * 100
            halo_gain_pct         = halo_gain_abs         / baseline_revenue_all * 100
        else:
            substitution_loss_pct = halo_gain_pct = 0.0

        net_basket = halo_gain_pct - substitution_loss_pct
        n_sub  = sum(1 for i in impacted_items if i["relationship"] == "SUBSTITUTE")
        n_comp = sum(1 for i in impacted_items if i["relationship"] == "COMPLEMENTARY")

        self._logger.info(
            "Cross-item impact computed",
            extra={
                "store_id": store_id, "source_item": source_item,
                "n_substitutes": n_sub, "n_complements": n_comp,
                "cannibalization_penalty_pct": round(substitution_loss_pct, 2),
                "operation": "simulate_cross_item_impact",
            },
        )
        return CrossItemImpact(
            source_item=source_item,
            impacted_items=impacted_items,
            total_substitution_loss_pct=round(substitution_loss_pct, 2),
            total_halo_gain_pct=round(halo_gain_pct, 2),
            net_basket_impact_pct=round(net_basket, 2),
            cannibalization_penalty_pct=round(substitution_loss_pct, 2),
            n_substitutes=n_sub,
            n_complements=n_comp,
        )

    def _classify(self, correlation: float) -> ItemRelationship:
        if correlation < SUBSTITUTE_CORRELATION_THRESHOLD:
            return ItemRelationship.SUBSTITUTE
        if correlation > COMPLEMENTARY_CORRELATION_THRESHOLD:
            return ItemRelationship.COMPLEMENTARY
        return ItemRelationship.INDEPENDENT
