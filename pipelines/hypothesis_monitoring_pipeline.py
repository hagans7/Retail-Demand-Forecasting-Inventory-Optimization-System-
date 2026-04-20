"""Hypothesis monitoring pipeline — weekly Monday 06:00."""
from __future__ import annotations
import asyncio
from datetime import date
from src.core.logging.logger import get_logger
_logger = get_logger(__name__)

async def run(run_date: str | None = None) -> dict:
    today = date.fromisoformat(run_date) if run_date else date.today()
    _logger.info("Hypothesis monitoring pipeline started",
                 extra={"run_date": str(today), "pipeline_name": "hypothesis_monitoring"})
    from src.providers.infrastructure import _session_factory
    from src.repositories.analytics_repository import AnalyticsRepository
    from src.services.run_hypothesis_monitor import RunHypothesisMonitorService

    async with _session_factory() as db:
        svc     = RunHypothesisMonitorService(AnalyticsRepository(db))
        results = await svc.execute(today)
        await AnalyticsRepository(db).save_hypothesis_results(results)

    n_alerts = sum(1 for r in results if r.alert_triggered)
    _logger.info("Hypothesis monitoring complete",
                 extra={"n_tests": len(results), "n_alerts": n_alerts,
                        "pipeline_name": "hypothesis_monitoring"})
    return {"status": "ok", "n_tests": len(results), "n_alerts": n_alerts}

if __name__ == "__main__":
    asyncio.run(run())
