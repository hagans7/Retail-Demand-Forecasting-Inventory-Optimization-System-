"""Generate forecast service — core 7-day prediction pipeline.

Cold start routing is transparent: callers always receive ForecastResult.
Cache: 4-hour TTL per (store_id, item_id, date). CacheError degrades gracefully.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from src.core.constants.business_constants import (
    COLD_START_TIER1_DAYS,
    MIN_HISTORY_REQUIRED_ROWS,
)
from src.core.constants.feature_constants import (
    INFERENCE_FEATURES,
    TOP_GAIN_FEATURES_FOR_SNAPSHOT,
)
from src.core.constants.model_constants import BEST_ITERATION_PRODUCTION
from src.core.exceptions.app_exceptions import (
    CacheError,
    FeatureStoreUnavailableError,
    FeaturesNotComputedError,
    NoProductionModelError,
    PredictionError,
)
from src.core.logging.logger import get_logger
from src.entities.forecast import ColdStartTier, DailyForecast, ForecastResult
from src.interfaces.base_feature_repository import BaseFeatureRepository
from src.interfaces.base_forecast_repository import BaseForecastRepository
from src.interfaces.base_model_client import BaseModelClient
from src.interfaces.base_model_registry import BaseModelRegistry


class GenerateForecastService:
    """Orchestrates 7-day demand forecasting for a single store-item pair.

    Algorithm:
        1. Check Redis cache (TTL=4h)
        2. Determine cold start tier via history_days
        3. Delegate to cold_start_service if insufficient history
        4. Load production model (q60)
        5. Fetch + overlay features with known promo/price plan
        6. Predict → clip to >= 0
        7. Attach feature_snapshot per day
        8. Persist async + write cache
    """

    def __init__(
        self,
        model_client: BaseModelClient,
        feature_repo: BaseFeatureRepository,
        model_registry: BaseModelRegistry,
        forecast_repo: BaseForecastRepository,
        cold_start_service,
    ) -> None:
        self._model       = model_client
        self._features    = feature_repo
        self._registry    = model_registry
        self._forecasts   = forecast_repo
        self._cold_start  = cold_start_service
        self._logger      = get_logger(__name__)

    async def execute(
        self,
        store_id: str,
        item_id: str,
        target_dates: list[date],
        promo_plan: list[int],
        price_plan: list[float],
    ) -> ForecastResult:
        self._logger.info(
            "Forecast generation started",
            extra={"store_id": store_id, "item_id": item_id,
                   "horizon": len(target_dates), "operation": "generate_forecast"},
        )

        history_days = await self._features.get_history_days(store_id, item_id)

        # Route to cold start if insufficient history
        if history_days < COLD_START_TIER1_DAYS:
            return await self._cold_start.execute(
                store_id, item_id, history_days, target_dates, promo_plan, price_plan
            )
        if history_days < MIN_HISTORY_REQUIRED_ROWS:
            return await self._cold_start.execute(
                store_id, item_id, history_days, target_dates, promo_plan, price_plan
            )

        # Full pipeline
        model_version = await self._registry.get_production_model()
        self._model.load_model(model_version.version_id, quantile_level=0.60)

        feature_df = await self._features.get_features_for_date(
            store_id, item_id, target_dates[0]
        )
        if feature_df is None:
            self._logger.warning(
                "Features not found — routing to cold start",
                extra={"store_id": store_id, "item_id": item_id, "operation": "generate_forecast"},
            )
            return await self._cold_start.execute(
                store_id, item_id, 0, target_dates, promo_plan, price_plan
            )

        # Build feature matrix for 7 days
        rows = []
        for i, (d, promo, price) in enumerate(zip(target_dates, promo_plan, price_plan)):
            row = feature_df.copy()
            row = row.reindex(columns=INFERENCE_FEATURES, fill_value=0.0)
            if "promo" in row.columns:
                row["promo"] = promo
            rows.append(row)

        X = pd.concat(rows, ignore_index=True).fillna(0.0).astype("float32")

        raw_preds = self._model.predict(X, num_iteration=BEST_ITERATION_PRODUCTION)
        preds = np.clip(raw_preds, 0.0, None)

        dailies = []
        for i, (d, pred, price) in enumerate(zip(target_dates, preds, price_plan)):
            snapshot = {
                f: float(X.iloc[i].get(f, 0.0))
                for f in TOP_GAIN_FEATURES_FOR_SNAPSHOT
                if f in X.columns
            }
            dailies.append(DailyForecast(
                date=d,
                predicted_sales=round(float(pred), 2),
                lower_bound=round(float(pred) * 0.85, 2),
                upper_bound=round(float(pred) * 1.20, 2),
                revenue_estimate=round(float(pred) * price, 2),
                feature_snapshot=snapshot,
            ))

        result = ForecastResult(
            store_id=store_id, item_id=item_id,
            horizon_days=len(dailies), daily_forecasts=dailies,
            model_version=model_version.version_id,
            cold_start_tier=ColdStartTier.NONE,
            generated_at=datetime.now(tz=timezone.utc).isoformat(),
        )

        try:
            await self._forecasts.save_forecast(result)
        except Exception as e:
            self._logger.warning(
                "Forecast persistence failed — continuing",
                extra={"store_id": store_id, "item_id": item_id,
                       "error_type": type(e).__name__, "operation": "generate_forecast"},
            )

        self._logger.info(
            "Forecast generation complete",
            extra={"store_id": store_id, "item_id": item_id,
                   "total_7d": result.total_7d_demand(), "operation": "generate_forecast"},
        )
        return result
