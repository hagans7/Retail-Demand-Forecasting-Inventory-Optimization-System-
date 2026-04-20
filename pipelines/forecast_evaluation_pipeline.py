"""Forecast evaluation pipeline — daily 08:00."""
from __future__ import annotations
import asyncio
from datetime import date, timedelta, datetime, timezone
from src.core.logging.logger import get_logger
_logger = get_logger(__name__)

async def run(run_date: str | None = None) -> dict:
    today     = date.fromisoformat(run_date) if run_date else date.today()
    eval_date = today - timedelta(days=1)
    _logger.info("Forecast evaluation pipeline started",
                 extra={"eval_date": str(eval_date), "pipeline_name": "forecast_evaluation"})
    from src.providers.infrastructure import _session_factory
    from src.repositories.forecast_repository import ForecastRepository
    from src.repositories.analytics_repository import AnalyticsRepository
    from src.repositories.monitoring_repository import MonitoringRepository
    from src.repositories.model_registry_repository import ModelRegistryRepository
    from src.services.evaluate_forecast_accuracy import EvaluateForecastAccuracyService

    async with _session_factory() as db:
        svc = EvaluateForecastAccuracyService(ForecastRepository(db), AnalyticsRepository(db))
        metrics = await svc.execute(eval_date)
        monitoring = MonitoringRepository(db)
        await monitoring.save_daily_metrics({
            "mae_overall":    metrics.get("mae_overall", 0),
            "mae_promo":      metrics.get("mae_promo", 0),
            "uf_promo_pct":   metrics.get("uf_promo_pct", 0),
            "mean_bias":      metrics.get("mean_bias", 0),
        })

    _logger.info("Forecast evaluation pipeline complete",
                 extra={**metrics, "pipeline_name": "forecast_evaluation"})
    return metrics

if __name__ == "__main__":
    asyncio.run(run())
