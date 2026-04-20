"""Evaluate forecast accuracy service — daily comparison of forecasts vs actuals.

Metrics computed:
    MAE overall (all pairs)
    MAE_promo  (promo days only — primary business metric)
    UF_promo   (underforecast rate on promo days)
    MeanBias   (signed mean error)
    naive_mae  (lag-7 baseline for relative comparison)

Alert rules (from business_constants, Category 3 overridable):
    MAE_promo > BASELINE_TEST_MAE_PROMO × (1 + MAE_PROMO_DEGRADATION_PCT/100) → alert
    UF_promo  > PROMO_UF_ALERT_THRESHOLD → alert
    abs(MeanBias) > FORECAST_BIAS_ALERT_THRESHOLD → alert
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.core.constants.business_constants import (
    FORECAST_BIAS_ALERT_THRESHOLD,
    MAE_PROMO_DEGRADATION_PCT,
    PROMO_UF_ALERT_THRESHOLD,
)
from src.core.constants.model_constants import BASELINE_TEST_MAE_PROMO
from src.core.logging.logger import get_logger
from src.interfaces.base_analytics_repository import BaseAnalyticsRepository
from src.interfaces.base_forecast_repository import BaseForecastRepository


class EvaluateForecastAccuracyService:
    """Compares yesterday's forecasts against today's actuals.

    Called daily by forecast_evaluation_pipeline (08:00).
    Writes metrics to monitoring_metrics table via monitoring_repository.
    """

    def __init__(
        self,
        forecast_repo: BaseForecastRepository,
        analytics_repo: BaseAnalyticsRepository,
    ) -> None:
        self._forecasts = forecast_repo
        self._analytics = analytics_repo
        self._logger    = get_logger(__name__)

    async def execute(self, evaluation_date: date | None = None) -> dict:
        eval_date = evaluation_date or (date.today() - timedelta(days=1))

        # 1. Load forecasts for eval_date
        forecast_rows = await self._forecasts.get_pending_evaluation(eval_date)
        if not forecast_rows:
            self._logger.warning(
                "No forecasts found for evaluation",
                extra={"eval_date": str(eval_date), "operation": "evaluate_forecast_accuracy"},
            )
            return {"eval_date": str(eval_date), "n_pairs": 0}

        # 2. Load actuals for eval_date
        actuals_df = await self._analytics.get_sales_for_period(eval_date, eval_date)
        if actuals_df.empty:
            self._logger.warning(
                "No actuals found for evaluation date",
                extra={"eval_date": str(eval_date), "operation": "evaluate_forecast_accuracy"},
            )
            return {"eval_date": str(eval_date), "n_pairs": 0}

        # 3. Join forecasts to actuals
        fc_df = pd.DataFrame(forecast_rows)
        merged = fc_df.merge(
            actuals_df[["store_id", "item_id", "sales", "promo"]].rename(
                columns={"sales": "actual_sales"}
            ),
            on=["store_id", "item_id"],
            how="inner",
        )
        if merged.empty:
            return {"eval_date": str(eval_date), "n_pairs": 0}

        preds   = merged["predicted_sales"].clip(lower=0).values
        actuals = merged["actual_sales"].clip(lower=0).values
        errors  = actuals - preds

        mae_overall = float(np.mean(np.abs(errors)))
        mean_bias   = float(np.mean(errors))

        promo_mask  = merged.get("promo", pd.Series([0]*len(merged))).values == 1
        if promo_mask.any():
            mae_promo = float(np.mean(np.abs(errors[promo_mask])))
            uf_promo  = float(np.mean(errors[promo_mask] > 0))   # actual > forecast
        else:
            mae_promo = mae_overall
            uf_promo  = 0.5

        # 4. Naive baseline (lag-7)
        naive_preds = merged.get("predicted_sales", pd.Series()).shift(7).fillna(actuals.mean()).values
        naive_mae   = float(np.mean(np.abs(actuals - naive_preds)))

        # 5. Alert thresholds
        mae_promo_alert = mae_promo > BASELINE_TEST_MAE_PROMO * (1 + MAE_PROMO_DEGRADATION_PCT / 100)
        uf_promo_alert  = uf_promo  > PROMO_UF_ALERT_THRESHOLD
        bias_alert      = abs(mean_bias) > FORECAST_BIAS_ALERT_THRESHOLD

        metrics = {
            "eval_date":      str(eval_date),
            "n_pairs":        len(merged),
            "mae_overall":    round(mae_overall, 4),
            "mae_promo":      round(mae_promo,   4),
            "uf_promo_pct":   round(uf_promo,    4),
            "mean_bias":      round(mean_bias,    4),
            "naive_mae":      round(naive_mae,    4),
            "mae_promo_alert":    mae_promo_alert,
            "uf_promo_alert":     uf_promo_alert,
            "bias_alert":         bias_alert,
            "retraining_recommended": mae_promo_alert or uf_promo_alert,
        }

        if any([mae_promo_alert, uf_promo_alert, bias_alert]):
            self._logger.warning(
                "Forecast accuracy alert triggered",
                extra={**metrics, "operation": "evaluate_forecast_accuracy"},
            )
        else:
            self._logger.info(
                "Forecast evaluation complete — within thresholds",
                extra={**metrics, "operation": "evaluate_forecast_accuracy"},
            )
        return metrics
