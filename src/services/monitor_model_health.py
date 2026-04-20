"""Monitor model health service — reads metrics and computes health status.

Reads rolling MAE from monitoring_metrics table.
Determines retraining_recommended based on thresholds.
Returns health dict consumed by /health endpoint and forecast_evaluation pipeline.
"""
from __future__ import annotations

from datetime import date

from src.core.constants.business_constants import MAE_PROMO_DEGRADATION_PCT, PROMO_UF_ALERT_THRESHOLD
from src.core.constants.model_constants import (
    BASELINE_TEST_MAE_PROMO,
    ROLLING_ALERT_WINDOW_DAYS,
    ROLLING_TREND_WINDOW_DAYS,
    RETRAINING_COOLDOWN_DAYS,
)
from src.core.logging.logger import get_logger
from src.interfaces.base_model_registry import BaseModelRegistry
from src.repositories.monitoring_repository import MonitoringRepository


class MonitorModelHealthService:
    """Computes health metrics for /health endpoint.

    Does NOT trigger retraining itself — only reports whether it's recommended.
    Retraining is triggered by forecast_evaluation_pipeline.
    """

    def __init__(
        self,
        monitoring_repo: MonitoringRepository,
        model_registry: BaseModelRegistry,
    ) -> None:
        self._monitoring = monitoring_repo
        self._registry   = model_registry
        self._logger     = get_logger(__name__)

    async def execute(self) -> dict:
        rolling_7d  = await self._monitoring.get_rolling_mae_promo(ROLLING_ALERT_WINDOW_DAYS)
        rolling_28d = await self._monitoring.get_rolling_mae_promo(ROLLING_TREND_WINDOW_DAYS)
        last_retrain= await self._monitoring.get_last_retraining_trigger_date()

        try:
            prod_model = await self._registry.get_production_model()
            model_version = prod_model.version_id
        except Exception:
            model_version = "NONE"

        # Retraining recommendation logic
        mae_degraded = (
            rolling_7d is not None and
            rolling_7d > BASELINE_TEST_MAE_PROMO * (1 + MAE_PROMO_DEGRADATION_PCT / 100)
        )
        cooldown_active = False
        if last_retrain:
            from datetime import datetime, timezone, timedelta
            days_since = (datetime.now(tz=timezone.utc) - last_retrain).days
            cooldown_active = days_since < RETRAINING_COOLDOWN_DAYS

        retraining_recommended = mae_degraded and not cooldown_active

        return {
            "model_version":          model_version,
            "rolling_7d_mae_promo":   round(float(rolling_7d),  4) if rolling_7d  else None,
            "rolling_28d_mae_promo":  round(float(rolling_28d), 4) if rolling_28d else None,
            "baseline_mae_promo":     BASELINE_TEST_MAE_PROMO,
            "retraining_recommended": retraining_recommended,
            "cooldown_active":        cooldown_active,
        }
