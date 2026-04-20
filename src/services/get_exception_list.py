"""Get exception list service — surfaces urgent anomaly alerts.

Exception types (ordered by severity):
    STOCKOUT_CRITICAL   — days_of_stock < 1 day
    STOCKOUT_HIGH       — days_of_stock < 3 days
    FORECAST_JUMP       — predicted_sales > P99_SALES_THRESHOLD (spike alert)
    ZERO_SALES_STREAK   — consecutive zero-sales >= ZERO_SALES_CONSECUTIVE_ALERT
    DEAD_STOCK          — zero-streak >= DEAD_STOCK_ZERO_STREAK_THRESHOLD
"""
from __future__ import annotations

from datetime import date

from src.core.constants.business_constants import (
    DEAD_STOCK_ZERO_STREAK_THRESHOLD,
    P99_SALES_THRESHOLD,
    STOCKOUT_CRITICAL_DAYS,
    STOCKOUT_HIGH_DAYS,
    ZERO_SALES_CONSECUTIVE_ALERT,
)
from src.core.logging.logger import get_logger
from src.interfaces.base_analytics_repository import BaseAnalyticsRepository
from src.interfaces.base_forecast_repository import BaseForecastRepository


class GetExceptionListService:
    """Returns ranked list of urgent store-item pairs requiring attention."""

    def __init__(
        self,
        forecast_repo: BaseForecastRepository,
        analytics_repo: BaseAnalyticsRepository,
    ) -> None:
        self._forecasts = forecast_repo
        self._analytics = analytics_repo
        self._logger    = get_logger(__name__)

    async def execute(self, target_date: date | None = None) -> list[dict]:
        today      = target_date or date.today()
        exceptions = []

        # FORECAST_JUMP: today's forecasts above P99 threshold
        try:
            fc_rows = await self._forecasts.get_pending_evaluation(today)
            for row in fc_rows:
                if row.get("predicted_sales", 0) >= P99_SALES_THRESHOLD:
                    exceptions.append({
                        "store_id":      row["store_id"],
                        "item_id":       row["item_id"],
                        "exception_type":"FORECAST_JUMP",
                        "severity":      "HIGH",
                        "value":         row["predicted_sales"],
                        "threshold":     P99_SALES_THRESHOLD,
                        "message":       f"Forecast {row['predicted_sales']:.0f} units exceeds P99={P99_SALES_THRESHOLD}",
                    })
        except Exception as e:
            self._logger.warning(f"Exception list: forecast check failed: {e}")

        # ZERO_SALES_STREAK: consecutive zero-sales anomalies
        try:
            zero_anomalies = await self._analytics.get_zero_sales_anomalies(ZERO_SALES_CONSECUTIVE_ALERT)
            for row in zero_anomalies:
                streak = row.get("streak_len", 0)
                etype  = "DEAD_STOCK" if streak >= DEAD_STOCK_ZERO_STREAK_THRESHOLD else "ZERO_SALES_STREAK"
                sev    = "CRITICAL"   if streak >= DEAD_STOCK_ZERO_STREAK_THRESHOLD else "HIGH"
                exceptions.append({
                    "store_id":      row["store_id"],
                    "item_id":       row["item_id"],
                    "exception_type": etype,
                    "severity":      sev,
                    "value":         streak,
                    "threshold":     ZERO_SALES_CONSECUTIVE_ALERT,
                    "message":       f"{streak} consecutive zero-sales days",
                })
        except Exception as e:
            self._logger.warning(f"Exception list: zero-sales check failed: {e}")

        # Sort: CRITICAL first, then HIGH, then value descending
        severity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        exceptions.sort(key=lambda e: (severity_rank.get(e["severity"], 9), -e["value"]))

        self._logger.info(
            "Exception list generated",
            extra={"n_exceptions": len(exceptions), "operation": "get_exception_list"},
        )
        return exceptions
