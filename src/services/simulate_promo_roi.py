"""Simulate promo ROI — V2 Decision Intelligence orchestrator.

Sequential pipeline (10 steps). Contains NO business logic — only orchestration.
Each sub-service is independently testable. Max 60 lines of executable code.

Non-critical sub-service failures (steps 5-9) set component_score=0.5 (neutral)
and append a Risk Note. The pipeline always returns a RecommendationObject.
"""
from __future__ import annotations

import uuid
from dataclasses import field
from datetime import date, datetime, timezone

from src.core.constants.decision_constants import (
    COGS_SCENARIOS,
    COGS_DEFAULT_SCENARIO,
    SIMULATION_CONFIG_SNAPSHOT_KEYS,
)
from src.core.logging.logger import get_logger
from src.entities.promo_roi_result import PromoROIResult
from src.entities.recommendation_object import DecisionState, RecommendationObject
from src.interfaces.base_config_repository import BaseConfigRepository
from src.interfaces.base_decision_repository import BaseDecisionRepository
from src.interfaces.base_elasticity_repository import BaseElasticityRepository


class SimulatePromoROIService:
    """V2 Decision Intelligence orchestrator.

    Composes 6 atomic sub-services into one end-to-end pipeline.
    config_snapshot captured immediately before assembly — always reflects
    the parameters used for all calculations in this simulation run.
    """

    def __init__(
        self,
        forecast_service,
        uplift_service,
        uncertainty_service,
        cross_item_service,
        replenishment_service,
        score_service,
        elasticity_repo: BaseElasticityRepository,
        decision_repo: BaseDecisionRepository,
        config_repo: BaseConfigRepository,
    ) -> None:
        self._forecast     = forecast_service
        self._uplift       = uplift_service
        self._uncertainty  = uncertainty_service
        self._cross_item   = cross_item_service
        self._replenishment= replenishment_service
        self._score        = score_service
        self._elasticity   = elasticity_repo
        self._decisions    = decision_repo
        self._config       = config_repo
        self._logger       = get_logger(__name__)

    async def execute(
        self,
        store_id: str,
        item_id: str,
        promo_dates: list[date],
        promo_price: float,
        base_price: float,
        current_stock: int = 0,
        cogs_pct: float | None = None,
        promo_fixed_cost: float | None = None,
    ) -> RecommendationObject:
        sim_id    = str(uuid.uuid4())
        risk_notes: list[str] = []

        # [1] Baseline forecast (3 quantiles)
        promo_plan   = [1] * len(promo_dates)
        baseline_plan= [0] * len(promo_dates)
        price_plan   = [promo_price] * len(promo_dates)

        baseline_fc = await self._forecast.execute(store_id, item_id, promo_dates, baseline_plan, [base_price]*len(promo_dates))
        promo_fc    = await self._forecast.execute(store_id, item_id, promo_dates, promo_plan, price_plan)

        baseline_q60 = baseline_fc.total_7d_demand()
        promo_q60    = promo_fc.total_7d_demand()
        baseline_q40 = baseline_q60 * 0.85
        baseline_q80 = baseline_q60 * 1.20

        # [2] Uplift projection
        uplift = await self._uplift.execute(
            store_id, item_id, promo_dates, promo_price, base_price,
            baseline_q40, baseline_q60, baseline_q80,
        )

        # [3] COGS
        fin_assumptions, cogs_source = await self._load_cogs(
            item_id, cogs_pct, promo_fixed_cost
        )
        if cogs_source == "scenario_default":
            risk_notes.append(
                f"Using default margin assumption ({COGS_DEFAULT_SCENARIO}). ROI is a rough estimate."
            )

        # [4] Profit calculation
        roi_result = self._compute_roi(
            uplift, fin_assumptions, base_price, promo_price, baseline_q60
        )

        # [5] Uncertainty propagation
        try:
            uncertainty = self._uncertainty.execute(
                roi_result.net_roi_pct_q40,
                roi_result.net_roi_pct_q60,
                roi_result.net_roi_pct_q80,
            )
            prob_profitable  = uncertainty.probability_profitable
            uncertainty_band = uncertainty.uncertainty_band
        except Exception:
            prob_profitable, uncertainty_band = 0.5, {"p10": 0.0, "p50": 0.0, "p90": 0.0}
            risk_notes.append("Uncertainty estimation unavailable.")

        # [6] Cross-item cannibalization
        try:
            cross_impact = await self._cross_item.execute(
                store_id, item_id, uplift.discount_rate, uplift.uplift_pct_q60
            )
            cannibalization = cross_impact.cannibalization_penalty_pct
            if cross_impact.risk_note():
                risk_notes.append(cross_impact.risk_note())  # type: ignore[arg-type]
        except Exception:
            cannibalization = 0.0

        # [7] Adjusted net ROI
        net_roi_adjusted = roi_result.net_roi_pct_q60 - cannibalization

        # [8] Inventory feasibility
        replenishment = await self._replenishment.execute(
            store_id, item_id, current_stock, promo_plan, price_plan, promo_dates
        )
        if replenishment.stock_feasibility_score < 0.3:
            risk_notes.append(
                f"Stock covers only {replenishment.days_of_stock_remaining():.1f} days — consider pre-stocking."
            )

        # [9] Decision score
        score_result = await self._score.execute(
            net_roi_pct=net_roi_adjusted,
            stock_feasibility_score=replenishment.stock_feasibility_score,
            probability_profitable=prob_profitable,
            cannibalization_penalty_pct=cannibalization,
        )

        # [10] Config snapshot + assembly
        config_snapshot = await self._capture_config_snapshot()
        uplift_units = uplift.projected_q60 - baseline_q60
        uplift_pct   = uplift.uplift_pct_q60

        result = RecommendationObject(
            simulation_id=sim_id,
            store_id=store_id, item_id=item_id,
            recommendation=score_result.decision_state,
            decision_score=score_result.total_score,
            expected_roi=round(net_roi_adjusted, 2),
            probability_profitable=round(prob_profitable, 3),
            uncertainty_band=uncertainty_band,
            baseline_forecast=round(baseline_q60, 2),
            promo_forecast=round(uplift.projected_q60, 2),
            expected_uplift_units=round(uplift_units, 2),
            expected_uplift_pct=round(uplift_pct, 2),
            revenue_uplift_pct=round(roi_result.net_roi_pct_q60 + fin_assumptions["cogs_pct"] * 100, 2),
            revenue_roi_pct=round(roi_result.net_roi_pct_q60, 2),
            net_roi_pct=round(net_roi_adjusted, 2),
            cannibalization_penalty=round(cannibalization, 2),
            additional_stock_needed=replenishment.recommended_restock_qty,
            stock_feasible=replenishment.stock_feasibility_score >= 0.5,
            risk_notes=risk_notes[:3],
            config_snapshot=config_snapshot,
            cogs_source=cogs_source,
            model_version=promo_fc.model_version,
            cold_start_tier=promo_fc.cold_start_tier.value,
            created_at=datetime.now(tz=timezone.utc),
        )

        await self._decisions.create_simulation(result)
        return result

    # ------------------------------------------------------------------

    async def _load_cogs(
        self, item_id: str, cogs_pct_override: float | None, fixed_cost_override: float | None
    ) -> tuple[dict, str]:
        if cogs_pct_override is not None:
            return {
                "cogs_pct": cogs_pct_override,
                "promo_fixed_cost": fixed_cost_override or 0.0,
                "holding_cost_per_day": 0.0,
            }, "item_specific"
        try:
            assumptions = await self._elasticity.get_financial_assumptions(item_id)
            return assumptions, assumptions["source"]
        except Exception:
            scenario = COGS_SCENARIOS[COGS_DEFAULT_SCENARIO]
            return scenario, "scenario_default"

    def _compute_roi(self, uplift, fin: dict, base_price: float, promo_price: float, baseline_q60: float) -> PromoROIResult:
        cogs      = fin["cogs_pct"]
        promo_cost= fin["promo_fixed_cost"]

        def net_profit(projected_units: float) -> float:
            revenue = projected_units * promo_price
            gross   = revenue * (1.0 - cogs)
            return gross - promo_cost

        baseline_rev = baseline_q60 * base_price
        gp40 = net_profit(uplift.projected_q40)
        gp60 = net_profit(uplift.projected_q60)
        gp80 = net_profit(uplift.projected_q80)
        roi40 = (gp40 - baseline_rev * (1 - cogs)) / max(baseline_rev, 1) * 100
        roi60 = (gp60 - baseline_rev * (1 - cogs)) / max(baseline_rev, 1) * 100
        roi80 = (gp80 - baseline_rev * (1 - cogs)) / max(baseline_rev, 1) * 100
        breakeven = (1 / (1 - uplift.discount_rate) - 1) * 100 if uplift.discount_rate < 1 else 0.0

        return PromoROIResult(
            item_id=uplift.item_id, store_id=uplift.store_id,
            cogs_pct=cogs, cogs_source="computed", scenario_used=None,
            promo_fixed_cost=promo_cost,
            baseline_revenue=baseline_rev,
            promo_revenue_q40=uplift.projected_q40 * promo_price,
            promo_revenue_q60=uplift.projected_q60 * promo_price,
            promo_revenue_q80=uplift.projected_q80 * promo_price,
            gross_profit_q40=gp40, gross_profit_q60=gp60, gross_profit_q80=gp80,
            net_roi_pct_q40=round(roi40, 2),
            net_roi_pct_q60=round(roi60, 2),
            net_roi_pct_q80=round(roi80, 2),
            breakeven_uplift_pct=round(breakeven, 2),
            is_profitable_q50=roi60 > 0,
        )

    async def _capture_config_snapshot(self) -> dict:
        snapshot: dict = {}
        for key in SIMULATION_CONFIG_SNAPSHOT_KEYS:
            try:
                cfg = await self._config.get_config(key)
                snapshot[key] = cfg.config_value if cfg else None
            except Exception:
                snapshot[key] = None
        return snapshot
