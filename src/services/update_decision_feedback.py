"""Update decision feedback — recalibration pipeline service.

Critical guard: simulations where promo was NOT executed in store
(promo=0 in actuals) are marked CANCELLED_IN_STORE and excluded from
all recalibration. This prevents model poisoning.

EMA update: new = 0.3 × actual_proxy + 0.7 × current_estimate
            (ELASTICITY_ROLLING_ALPHA = 0.3)

Category 4 only: updates item_elasticity_observed.
LightGBM model artifacts are NEVER modified by this service.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from src.core.constants.decision_constants import (
    ELASTICITY_DEVIATION_FLAG_PCT,
    ELASTICITY_ROLLING_ALPHA,
    FEEDBACK_LOOP_MAX_LOOKBACK_DAYS,
    FEEDBACK_LOOP_MIN_LOOKBACK_DAYS,
)
from src.core.exceptions.app_exceptions import SimulationUnresolvableError
from src.core.logging.logger import get_logger
from src.entities.decision_feedback_record import DecisionFeedbackRecord, FeedbackStatus
from src.interfaces.base_analytics_repository import BaseAnalyticsRepository
from src.interfaces.base_decision_repository import BaseDecisionRepository
from src.interfaces.base_elasticity_repository import BaseElasticityRepository


class UpdateDecisionFeedbackService:
    """Recalibrates business parameters from predicted vs actual promo outcomes.

    Called by feedback_recalibration_pipeline weekly (Monday 07:30).
    Processes simulations created 7-14 days ago with status=PENDING.

    Category 4 parameters updated: item_elasticity_observed only.
    Model artifacts and Category 1-3 parameters are NOT modified.
    """

    def __init__(
        self,
        decision_repo: BaseDecisionRepository,
        analytics_repo: BaseAnalyticsRepository,
        elasticity_repo: BaseElasticityRepository,
    ) -> None:
        self._decisions  = decision_repo
        self._analytics  = analytics_repo
        self._elasticity = elasticity_repo
        self._logger     = get_logger(__name__)

    async def execute(self) -> dict:
        """Process all pending simulations in the feedback window.

        Returns summary: {n_processed, n_resolved, n_cancelled, n_flagged}
        """
        pending = await self._decisions.get_pending_feedback(
            min_age_days=FEEDBACK_LOOP_MIN_LOOKBACK_DAYS,
            max_age_days=FEEDBACK_LOOP_MAX_LOOKBACK_DAYS,
        )

        n_resolved = n_cancelled = n_flagged = 0

        for sim in pending:
            record = await self._process_single(sim)
            if record.status == FeedbackStatus.CANCELLED_IN_STORE:
                n_cancelled += 1
            elif record.status == FeedbackStatus.RESOLVED:
                n_resolved += 1
                if record.flagged_for_review:
                    n_flagged += 1

        summary = {
            "n_processed": len(pending),
            "n_resolved":  n_resolved,
            "n_cancelled": n_cancelled,
            "n_flagged":   n_flagged,
        }
        self._logger.info(
            "Feedback recalibration complete",
            extra={**summary, "operation": "update_decision_feedback"},
        )
        return summary

    # ------------------------------------------------------------------

    async def _process_single(self, sim) -> DecisionFeedbackRecord:
        """Process one simulation. Returns feedback record with final status."""
        from datetime import timedelta

        # Determine date range from simulation (use predicted_uplift_pct as proxy indicator)
        created_at = sim.created_at
        end_date   = created_at.date()
        start_date = end_date - timedelta(days=7)

        try:
            actuals_df = await self._analytics.get_sales_for_period(start_date, end_date)
        except Exception as e:
            self._logger.warning(
                "Could not fetch actuals — skipping simulation",
                extra={"simulation_id": sim.simulation_id, "error": str(e),
                       "operation": "update_decision_feedback"},
            )
            return DecisionFeedbackRecord(
                simulation_id=sim.simulation_id,
                item_id=sim.item_id, store_id=sim.store_id,
                predicted_uplift_pct=sim.expected_uplift_pct,
                status=FeedbackStatus.UNRESOLVED,
            )

        # CRITICAL VALIDATION: check promo was actually executed
        pair_actuals = actuals_df[
            (actuals_df["store_id"] == sim.store_id) &
            (actuals_df["item_id"]  == sim.item_id)
        ] if not actuals_df.empty else pd.DataFrame()

        promo_executed = (
            not pair_actuals.empty
            and int(pair_actuals["promo"].sum()) > 0
        )

        if not promo_executed:
            # Promo never ran in store — do NOT recalibrate (model poisoning prevention)
            await self._decisions.update_resolution(
                sim.simulation_id, FeedbackStatus.CANCELLED_IN_STORE,
                {"reason": "promo_not_executed_in_store"}
            )
            self._logger.warning(
                "Simulation marked CANCELLED_IN_STORE — promo not executed",
                extra={"simulation_id": sim.simulation_id,
                       "store_id": sim.store_id, "item_id": sim.item_id,
                       "operation": "update_decision_feedback"},
            )
            return DecisionFeedbackRecord(
                simulation_id=sim.simulation_id,
                item_id=sim.item_id, store_id=sim.store_id,
                predicted_uplift_pct=sim.expected_uplift_pct,
                status=FeedbackStatus.CANCELLED_IN_STORE,
            )

        # Compute actual uplift
        promo_rows = pair_actuals[pair_actuals["promo"] == 1]
        normal_rows = pair_actuals[pair_actuals["promo"] == 0]

        avg_promo  = float(promo_rows["sales"].mean())   if not promo_rows.empty  else 0.0
        avg_normal = float(normal_rows["sales"].mean())  if not normal_rows.empty else 0.0

        if avg_normal > 0:
            actual_uplift_pct = (avg_promo - avg_normal) / avg_normal * 100
        else:
            actual_uplift_pct = 0.0

        predicted = sim.expected_uplift_pct or 0.0
        deviation = actual_uplift_pct - predicted
        flagged   = abs(deviation) > ELASTICITY_DEVIATION_FLAG_PCT

        # EMA recalibration of elasticity
        if pair_actuals.get("price") is not None and not pair_actuals.empty:
            discount_col = pair_actuals.get("price", pd.Series(dtype=float))
            avg_price_promo  = float(promo_rows["price"].mean())  if "price" in promo_rows else 0.0
            avg_price_normal = float(normal_rows["price"].mean()) if "price" in normal_rows else avg_price_promo

            if avg_price_normal > 0 and avg_price_promo > 0:
                discount_rate = (avg_price_normal - avg_price_promo) / avg_price_normal
                if discount_rate > 0:
                    actual_elasticity_proxy = (actual_uplift_pct / 100) / discount_rate
                    await self._elasticity.update_elasticity_ema(
                        sim.item_id, sim.store_id,
                        actual_elasticity_proxy, source="feedback_loop"
                    )

        actual_outcome = {
            "actual_uplift_pct": round(actual_uplift_pct, 2),
            "deviation_pct":     round(deviation, 2),
            "flagged_for_review": flagged,
            "human_decision":    None,
        }
        await self._decisions.update_resolution(
            sim.simulation_id, FeedbackStatus.RESOLVED, actual_outcome
        )

        if flagged:
            self._logger.warning(
                "High deviation flagged for review",
                extra={
                    "simulation_id": sim.simulation_id,
                    "item_id": sim.item_id,
                    "deviation_pct": round(deviation, 2),
                    "operation": "update_decision_feedback",
                },
            )
        return DecisionFeedbackRecord(
            simulation_id=sim.simulation_id,
            item_id=sim.item_id, store_id=sim.store_id,
            predicted_uplift_pct=predicted,
            actual_uplift_pct=round(actual_uplift_pct, 2),
            deviation_pct=round(deviation, 2),
            status=FeedbackStatus.RESOLVED,
            flagged_for_review=flagged,
        )
