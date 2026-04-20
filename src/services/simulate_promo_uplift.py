"""Simulate promo uplift — quantile-aware, elasticity-adjusted projection.

Enhancement over V1: incorporates item-specific price elasticity from
item_elasticity_observed (recalibrated by feedback loop weekly).

Algorithm:
    1. Load baseline forecast ALL THREE quantiles (q40, q60, q80)
    2. Load item elasticity from item_elasticity_observed
    3. Compute discount_rate from promo_price vs base_price
    4. Apply elasticity multiplier (only for elastic items; coef < -0.10)
    5. Apply weekday adjustment (±5%) per day
    6. Apply promo_streak decay (Day4+: 0.85×)
    7. Return per-quantile projections
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.core.constants.analytics_constants import (
    BASELINE_MATCHED_WINDOW_UPLIFT,
    ELASTICITY_ELASTIC_ITEM_THRESHOLD,
)
from src.core.constants.feature_constants import FORECAST_HORIZON_DAYS
from src.core.exceptions.app_exceptions import ElasticityDataUnavailableError
from src.core.logging.logger import get_logger
from src.interfaces.base_elasticity_repository import BaseElasticityRepository
from src.interfaces.base_feature_repository import BaseFeatureRepository
from src.interfaces.base_model_client import BaseModelClient
from src.interfaces.base_model_registry import BaseModelRegistry


@dataclass
class PromoUpliftResult:
    """Per-quantile projected demand with promo active."""
    store_id       : str
    item_id        : str
    baseline_q40   : float
    baseline_q60   : float
    baseline_q80   : float
    projected_q40  : float
    projected_q60  : float
    projected_q80  : float
    uplift_pct_q60 : float
    elasticity_coef: float
    discount_rate  : float
    is_elastic     : bool


class SimulatePromoUpliftService:
    """Projects quantile-aware demand uplift for a promo scenario.

    Weekday adjustment uses PROMO_BEST_WEEKDAY_UNIT from analytics constants.
    Streak decay: Day1=1.0, Day2=0.95, Day3=0.90, Day4+=0.85.
    """

    _WEEKDAY_BEST  = 2   # Wednesday — from analytics_validation notebook
    _WEEKDAY_WORST = 5   # Saturday
    _WD_BOOST      = 1.05
    _WD_DAMP       = 0.95
    _STREAK_DECAY  = {1: 1.0, 2: 0.95, 3: 0.90}
    _STREAK_DEFAULT = 0.85

    def __init__(
        self,
        model_client: BaseModelClient,
        feature_repo: BaseFeatureRepository,
        model_registry: BaseModelRegistry,
        elasticity_repo: BaseElasticityRepository,
    ) -> None:
        self._model       = model_client
        self._features    = feature_repo
        self._registry    = model_registry
        self._elasticity  = elasticity_repo
        self._logger      = get_logger(__name__)

    async def execute(
        self,
        store_id: str,
        item_id: str,
        promo_dates: list[date],
        promo_price: float,
        base_price: float,
        baseline_forecast_q40: float,
        baseline_forecast_q60: float,
        baseline_forecast_q80: float,
    ) -> PromoUpliftResult:
        # 1. Elasticity lookup
        elasticity_coef = await self._load_elasticity(store_id, item_id)
        is_elastic = elasticity_coef < ELASTICITY_ELASTIC_ITEM_THRESHOLD

        # 2. Discount rate
        discount_rate = (base_price - promo_price) / base_price if base_price > 0 else 0.0

        # 3. Base uplift from validated baseline
        base_uplift = BASELINE_MATCHED_WINDOW_UPLIFT / 100  # 0.50

        # 4. Elasticity multiplier — only amplifies for elastic items
        if is_elastic and abs(elasticity_coef) > 0:
            # Normalize to 20% discount baseline from analytics
            elasticity_multiplier = 1.0 + abs(elasticity_coef) * (discount_rate / 0.20)
        else:
            elasticity_multiplier = 1.0

        # 5. Weekday + streak adjustments applied per-day then averaged
        n_days = len(promo_dates)
        day_multipliers = []
        for streak_day, d in enumerate(promo_dates, start=1):
            weekday = d.weekday()
            wd_mult = self._WD_BOOST if weekday == self._WEEKDAY_BEST else (
                self._WD_DAMP if weekday == self._WEEKDAY_WORST else 1.0
            )
            streak_mult = self._STREAK_DECAY.get(streak_day, self._STREAK_DEFAULT)
            day_multipliers.append(wd_mult * streak_mult)

        avg_multiplier = sum(day_multipliers) / len(day_multipliers) if day_multipliers else 1.0
        total_uplift = base_uplift * elasticity_multiplier * avg_multiplier

        # 6. Apply per-quantile
        projected_q40 = baseline_forecast_q40 * (1 + total_uplift)
        projected_q60 = baseline_forecast_q60 * (1 + total_uplift)
        projected_q80 = baseline_forecast_q80 * (1 + total_uplift)
        uplift_pct_q60 = (projected_q60 - baseline_forecast_q60) / max(baseline_forecast_q60, 1) * 100

        self._logger.info(
            "Promo uplift computed",
            extra={
                "store_id": store_id, "item_id": item_id,
                "discount_rate": round(discount_rate, 3),
                "elasticity_coef": round(elasticity_coef, 4),
                "is_elastic": is_elastic,
                "uplift_pct_q60": round(uplift_pct_q60, 2),
                "operation": "simulate_promo_uplift",
            },
        )
        return PromoUpliftResult(
            store_id=store_id, item_id=item_id,
            baseline_q40=baseline_forecast_q40,
            baseline_q60=baseline_forecast_q60,
            baseline_q80=baseline_forecast_q80,
            projected_q40=max(0.0, projected_q40),
            projected_q60=max(0.0, projected_q60),
            projected_q80=max(0.0, projected_q80),
            uplift_pct_q60=uplift_pct_q60,
            elasticity_coef=elasticity_coef,
            discount_rate=discount_rate,
            is_elastic=is_elastic,
        )

    async def _load_elasticity(self, store_id: str, item_id: str) -> float:
        """Load observed elasticity; fall back to global baseline if missing."""
        try:
            coef = await self._elasticity.get_elasticity(item_id, store_id)
            if coef is not None:
                return coef
        except Exception:
            pass
        from src.core.constants.analytics_constants import BASELINE_PRICE_SALES_CORR
        self._logger.warning(
            "Elasticity not found — using global baseline",
            extra={"store_id": store_id, "item_id": item_id,
                   "operation": "simulate_promo_uplift"},
        )
        return BASELINE_PRICE_SALES_CORR
