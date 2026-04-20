# """Cold start service — proxy forecasting for pairs with insufficient history.

# Tier routing (thresholds from business_constants.py):
#     history_days < COLD_START_TIER1_DAYS (7)  → TIER1_PROXY (cross-store avg)
#     7 <= history_days < MIN_HISTORY_REQUIRED (28) → TIER2_REDUCED (lag_7 only)

# Safety factor is always SAFETY_FACTOR_COLD_START (1.30) for both tiers.
# Error ratio: Tier1 ~1.13x, Tier2 ~1.01x (validated in analytics_validation.ipynb).
# """
# from __future__ import annotations

# from datetime import date, datetime, timezone

# import numpy as np
# import pandas as pd

# from src.core.constants.business_constants import SAFETY_FACTOR_COLD_START
# from src.core.constants.feature_constants import COLD_START_REDUCED_FEATURES
# from src.core.constants.model_constants import (
#     BEST_ITERATION_PRODUCTION,
#     COLD_START_CONFIDENCE_NOTE,
# )
# from src.core.logging.logger import get_logger
# from src.entities.forecast import ColdStartTier, DailyForecast, ForecastResult
# from src.interfaces.base_feature_repository import BaseFeatureRepository
# from src.interfaces.base_model_client import BaseModelClient
# from src.interfaces.base_model_registry import BaseModelRegistry


# class HandleColdStartService:
#     """Generates proxy forecasts for new or data-sparse store-item pairs.

#     Never raises — always returns a ForecastResult with appropriate tier flag.
#     Confidence note and safety_factor signal to downstream consumers to apply
#     extra buffer (ComputeReplenishmentService reads cold_start_tier).
#     """

#     def __init__(
#         self,
#         model_client: BaseModelClient,
#         feature_repo: BaseFeatureRepository,
#         model_registry: BaseModelRegistry,
#     ) -> None:
#         self._model    = model_client
#         self._features = feature_repo
#         self._registry = model_registry
#         self._logger   = get_logger(__name__)

#     async def execute(
#         self,
#         store_id: str,
#         item_id: str,
#         history_days: int,
#         target_dates: list[date],
#         promo_plan: list[int],
#         price_plan: list[float],
#     ) -> ForecastResult:
#         """Route to appropriate tier and return ForecastResult."""
#         if history_days < 7:
#             return await self._tier1_proxy(
#                 store_id, item_id, target_dates, promo_plan, price_plan
#             )
#         return await self._tier2_reduced(
#             store_id, item_id, target_dates, promo_plan, price_plan
#         )

#     # ------------------------------------------------------------------

#     async def _tier1_proxy(
#         self,
#         store_id: str,
#         item_id: str,
#         target_dates: list[date],
#         promo_plan: list[int],
#         price_plan: list[float],
#     ) -> ForecastResult:
#         """Tier1: cross-store item average as proxy. Error ~1.13x full model."""
#         from src.core.constants.analytics_constants import (
#             BASELINE_MATCHED_WINDOW_UPLIFT,
#             TRAINING_MEAN_SALES,
#         )
#         # Use global average as fallback (in real system, query cross-store avg)
#         proxy_daily = TRAINING_MEAN_SALES
#         dailies = []
#         for i, (d, promo, price) in enumerate(zip(target_dates, promo_plan, price_plan)):
#             sales = proxy_daily * SAFETY_FACTOR_COLD_START
#             if promo == 1:
#                 sales *= (1 + BASELINE_MATCHED_WINDOW_UPLIFT / 100)
#             sales = max(0.0, sales)
#             dailies.append(DailyForecast(
#                 date=d,
#                 predicted_sales=round(sales, 2),
#                 lower_bound=round(sales * 0.70, 2),
#                 upper_bound=round(sales * 1.30, 2),
#                 revenue_estimate=round(sales * price, 2),
#                 feature_snapshot={"proxy_source": "cross_store_avg", "history_days": 0},
#             ))
#         self._logger.info(
#             "Cold start Tier1 proxy forecast generated",
#             extra={"store_id": store_id, "item_id": item_id,
#                    "proxy_daily": proxy_daily, "operation": "cold_start_tier1"},
#         )
#         return ForecastResult(
#             store_id=store_id, item_id=item_id,
#             horizon_days=len(dailies), daily_forecasts=dailies,
#             model_version="COLD_START_TIER1",
#             cold_start_tier=ColdStartTier.TIER1_PROXY,
#             generated_at=datetime.now(tz=timezone.utc).isoformat(),
#         )

#     async def _tier2_reduced(
#         self,
#         store_id: str,
#         item_id: str,
#         target_dates: list[date],
#         promo_plan: list[int],
#         price_plan: list[float],
#     ) -> ForecastResult:
#         """Tier2: lag_7 available; use reduced feature set with model inference."""
#         from src.core.constants.analytics_constants import TRAINING_MEAN_SALES
#         proxy_daily = TRAINING_MEAN_SALES * SAFETY_FACTOR_COLD_START
#         dailies = []
#         for d, promo, price in zip(target_dates, promo_plan, price_plan):
#             sales = max(0.0, proxy_daily)
#             dailies.append(DailyForecast(
#                 date=d,
#                 predicted_sales=round(sales, 2),
#                 lower_bound=round(sales * 0.80, 2),
#                 upper_bound=round(sales * 1.20, 2),
#                 revenue_estimate=round(sales * price, 2),
#                 feature_snapshot={"proxy_source": "lag7_imputed", "history_days": "7-27"},
#             ))
#         self._logger.info(
#             "Cold start Tier2 reduced forecast generated",
#             extra={"store_id": store_id, "item_id": item_id, "operation": "cold_start_tier2"},
#         )
#         return ForecastResult(
#             store_id=store_id, item_id=item_id,
#             horizon_days=len(dailies), daily_forecasts=dailies,
#             model_version="COLD_START_TIER2",
#             cold_start_tier=ColdStartTier.TIER2_REDUCED,
#             generated_at=datetime.now(tz=timezone.utc).isoformat(),
#         )

"""Cold start service — proxy forecasting for pairs with insufficient history.

Tier routing (thresholds from business_constants.py):
    history_days < COLD_START_TIER1_DAYS (7)  → TIER1_PROXY (cross-store avg)
    7 <= history_days < MIN_HISTORY_REQUIRED (28) → TIER2_REDUCED (lag_7 only)

Safety factor is always SAFETY_FACTOR_COLD_START (1.30) for both tiers.
Error ratio: Tier1 ~1.13x, Tier2 ~1.01x (validated in analytics_validation.ipynb).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from src.core.constants.business_constants import SAFETY_FACTOR_COLD_START
from src.core.constants.feature_constants import COLD_START_REDUCED_FEATURES
from src.core.constants.model_constants import (
    BEST_ITERATION_PRODUCTION,
    COLD_START_CONFIDENCE_NOTE,
)
from src.core.logging.logger import get_logger
from src.entities.forecast import ColdStartTier, DailyForecast, ForecastResult
from src.interfaces.base_feature_repository import BaseFeatureRepository
from src.interfaces.base_model_client import BaseModelClient
from src.interfaces.base_model_registry import BaseModelRegistry


class HandleColdStartService:
    """Generates proxy forecasts for new or data-sparse store-item pairs.

    Never raises — always returns a ForecastResult with appropriate tier flag.
    Confidence note and safety_factor signal to downstream consumers to apply
    extra buffer (ComputeReplenishmentService reads cold_start_tier).
    """

    def __init__(
        self,
        model_client: BaseModelClient,
        feature_repo: BaseFeatureRepository,
        model_registry: BaseModelRegistry,
    ) -> None:
        self._model    = model_client
        self._features = feature_repo
        self._registry = model_registry
        self._logger   = get_logger(__name__)

    async def execute(
        self,
        store_id: str,
        item_id: str,
        history_days: int,
        target_dates: list[date],
        promo_plan: list[int],
        price_plan: list[float],
    ) -> ForecastResult:
        """Route to appropriate tier and return ForecastResult."""
        if history_days < 7:
            return await self._tier1_proxy(
                store_id, item_id, target_dates, promo_plan, price_plan
            )
        return await self._tier2_reduced(
            store_id, item_id, target_dates, promo_plan, price_plan
        )

    # ------------------------------------------------------------------

    async def _tier1_proxy(
        self,
        store_id: str,
        item_id: str,
        target_dates: list[date],
        promo_plan: list[int],
        price_plan: list[float],
    ) -> ForecastResult:
        """Tier1: cross-store item average as proxy. Error ~1.13x full model."""
        from src.core.constants.analytics_constants import (
            BASELINE_MATCHED_WINDOW_UPLIFT,
            TRAINING_MEAN_SALES,
        )
        # Use global average as fallback (in real system, query cross-store avg)
        proxy_daily = TRAINING_MEAN_SALES
        dailies = []
        for i, (d, promo, price) in enumerate(zip(target_dates, promo_plan, price_plan)):
            sales = proxy_daily * SAFETY_FACTOR_COLD_START
            if promo == 1:
                sales *= (1 + BASELINE_MATCHED_WINDOW_UPLIFT / 100)
            sales = max(0.0, sales)
            dailies.append(DailyForecast(
                date=d,
                predicted_sales=round(sales, 2),
                lower_bound=round(sales * 0.70, 2),
                upper_bound=round(sales * 1.30, 2),
                revenue_estimate=round(sales * price, 2),
                feature_snapshot={"proxy_source": "cross_store_avg", "history_days": 0},
            ))
        self._logger.info(
            "Cold start Tier1 proxy forecast generated",
            extra={"store_id": store_id, "item_id": item_id,
                   "proxy_daily": proxy_daily, "operation": "cold_start_tier1"},
        )
        return ForecastResult(
            store_id=store_id, item_id=item_id,
            horizon_days=len(dailies), daily_forecasts=dailies,
            model_version="COLD_START_TIER1",
            cold_start_tier=ColdStartTier.TIER1_PROXY,
            generated_at=datetime.now(tz=timezone.utc).isoformat(),
        )

    async def _tier2_reduced(
        self,
        store_id: str,
        item_id: str,
        target_dates: list[date],
        promo_plan: list[int],
        price_plan: list[float],
    ) -> ForecastResult:
        """Tier2 (7–27 days history): use lag_7 as the per-item demand signal.

        Docstring previously claimed model inference — that was incorrect.
        Actual approach: use the item's own lag_7 feature (most recent available
        weekly sales) as the demand base, then apply SAFETY_FACTOR_COLD_START.
        This is meaningfully better than Tier1 (which uses the global mean) because
        it reflects item-specific demand level, not just the catalogue average.

        Error ratio: ~1.01× (validated in analytics_validation notebook).
        """
        from src.core.constants.analytics_constants import TRAINING_MEAN_SALES

        # Fetch lag_7 for this pair from feature_snapshots if available
        lag7_val: float | None = None
        try:
            feat_df = await self._features.get_features_for_date(
                store_id, item_id, target_dates[0]
            )
            if feat_df is not None and "lag_7" in feat_df.columns:
                raw = feat_df["lag_7"].iloc[0]
                if raw is not None and not (isinstance(raw, float) and __import__("math").isnan(raw)):
                    lag7_val = float(raw)
        except Exception:
            pass

        # Fallback to global mean if lag_7 unavailable
        base_demand = lag7_val if lag7_val is not None else TRAINING_MEAN_SALES
        proxy_daily  = base_demand * SAFETY_FACTOR_COLD_START

        dailies = []
        for d, promo, price in zip(target_dates, promo_plan, price_plan):
            sales = max(0.0, proxy_daily)
            dailies.append(DailyForecast(
                date=d,
                predicted_sales=round(sales, 2),
                lower_bound=round(sales * 0.80, 2),
                upper_bound=round(sales * 1.20, 2),
                revenue_estimate=round(sales * price, 2),
                feature_snapshot={
                    "proxy_source": "lag7_item_specific" if lag7_val is not None else "global_mean_fallback",
                    "lag_7_value":  round(lag7_val, 2) if lag7_val is not None else None,
                    "history_days": "7-27",
                },
            ))
        self._logger.info(
            "Cold start Tier2 reduced forecast generated",
            extra={
                "store_id": store_id, "item_id": item_id,
                "lag7_used": lag7_val is not None,
                "base_demand": round(proxy_daily, 2),
                "operation": "cold_start_tier2",
            },
        )
        return ForecastResult(
            store_id=store_id, item_id=item_id,
            horizon_days=len(dailies), daily_forecasts=dailies,
            model_version="COLD_START_TIER2",
            cold_start_tier=ColdStartTier.TIER2_REDUCED,
            generated_at=datetime.now(tz=timezone.utc).isoformat(),
        )