"""Compute replenishment service — translates forecast into inventory signal."""
from __future__ import annotations

import math
from datetime import date

from src.core.constants.business_constants import (
    SAFETY_FACTOR_COLD_START,
    SAFETY_FACTOR_NORMAL,
    SAFETY_FACTOR_PROMO,
    STOCKOUT_CRITICAL_DAYS,
    STOCKOUT_HIGH_DAYS,
    STOCKOUT_MEDIUM_DAYS,
)
from src.core.logging.logger import get_logger
from src.entities.forecast import ColdStartTier
from src.entities.replenishment import ReplenishmentSignal, StockoutRisk
from src.interfaces.base_config_repository import BaseConfigRepository


class ComputeReplenishmentService:
    """Translates forecast into actionable inventory signal.

    Enhancement over V1: stock_feasibility_score (0.0-1.0) output
    consumed by V2 ComputeDecisionScoreService.
    """

    def __init__(self, forecast_service, config_repo: BaseConfigRepository) -> None:
        self._forecast = forecast_service
        self._config   = config_repo
        self._logger   = get_logger(__name__)

    async def execute(
        self,
        store_id: str,
        item_id: str,
        current_stock: int,
        promo_plan: list[int],
        price_plan: list[float],
        target_dates: list[date] | None = None,
    ) -> ReplenishmentSignal:
        from datetime import date as dt, timedelta
        if target_dates is None:
            today = dt.today()
            target_dates = [today + timedelta(days=i) for i in range(7)]

        forecast = await self._forecast.execute(
            store_id, item_id, target_dates, promo_plan, price_plan
        )

        # Runtime safety factor override from business_configs
        has_promo = any(p == 1 for p in promo_plan)
        safety = await self._get_safety_factor(forecast.cold_start_tier, has_promo)

        forecast_7d   = forecast.total_7d_demand()
        required      = forecast_7d * safety
        restock_qty   = max(0, math.ceil(required - current_stock))
        risk          = self._classify_risk(forecast_7d, current_stock)
        feasibility   = self._compute_feasibility_score(current_stock, required)
        reason_codes  = self._build_reason_codes(has_promo, risk, forecast)

        return ReplenishmentSignal(
            store_id=store_id,
            item_id=item_id,
            forecast_7d=forecast_7d,
            current_stock=current_stock,
            safety_factor=safety,
            recommended_restock_qty=restock_qty,
            stockout_risk=risk,
            stock_feasibility_score=feasibility,
            reason_codes=reason_codes,
            cold_start_tier=forecast.cold_start_tier.value,
        )

    # ------------------------------------------------------------------

    async def _get_safety_factor(
        self, tier: ColdStartTier, has_promo: bool
    ) -> float:
        if tier != ColdStartTier.NONE:
            cfg = await self._config.get_config("SAFETY_FACTOR_COLD_START")
            return cfg.config_value if cfg else SAFETY_FACTOR_COLD_START
        if has_promo:
            cfg = await self._config.get_config("SAFETY_FACTOR_PROMO")
            return cfg.config_value if cfg else SAFETY_FACTOR_PROMO
        cfg = await self._config.get_config("SAFETY_FACTOR_NORMAL")
        return cfg.config_value if cfg else SAFETY_FACTOR_NORMAL

    def _classify_risk(self, forecast_7d: float, current_stock: int) -> StockoutRisk:
        daily_avg = forecast_7d / 7
        if daily_avg <= 0:
            return StockoutRisk.LOW
        days_cover = current_stock / daily_avg
        if days_cover < STOCKOUT_CRITICAL_DAYS:
            return StockoutRisk.CRITICAL
        if days_cover < STOCKOUT_HIGH_DAYS:
            return StockoutRisk.HIGH
        if days_cover < STOCKOUT_MEDIUM_DAYS:
            return StockoutRisk.MEDIUM
        return StockoutRisk.LOW

    def _compute_feasibility_score(self, current_stock: int, required: float) -> float:
        """0.0 = completely infeasible; 1.0 = stock exceeds requirement."""
        if required <= 0:
            return 1.0
        ratio = current_stock / required
        return min(1.0, max(0.0, ratio))

    def _build_reason_codes(self, has_promo: bool, risk: StockoutRisk, forecast) -> list[str]:
        codes = []
        if has_promo:
            codes.append("promo_planned")
        if risk in (StockoutRisk.CRITICAL, StockoutRisk.HIGH):
            codes.append("critical_stock_level")
        if forecast.is_cold_start():
            codes.append(f"cold_start_{forecast.cold_start_tier.value.lower()}")
        peak = forecast.peak_day()
        if peak.predicted_sales > 50:
            codes.append("high_demand_day_forecast")
        return codes
