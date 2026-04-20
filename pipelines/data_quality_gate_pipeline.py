"""Data quality gate pipeline — daily 00:30.

Runs pre-flight checks. Blocks downstream pipelines if CRITICAL checks fail.
Triggers feature_engineering_pipeline on success.
"""
from __future__ import annotations
import asyncio
from datetime import date, datetime, timezone
from src.core.logging.logger import get_logger
_logger = get_logger(__name__)

async def run(run_date: str | None = None) -> dict:
    today = date.fromisoformat(run_date) if run_date else date.today()
    _logger.info("Data quality gate pipeline started",
                 extra={"run_date": str(today), "pipeline_name": "data_quality_gate"})
    from src.providers.infrastructure import _session_factory
    from src.repositories.analytics_repository import AnalyticsRepository
    from src.services.run_data_quality_gate import RunDataQualityGateService

    async with _session_factory() as db:
        svc   = RunDataQualityGateService(AnalyticsRepository(db))
        event = await svc.execute(today)

    if event.pipeline_blocked:
        _logger.error(
            "Data quality gate FAILED — downstream pipelines blocked",
            extra={"failed_checks": [c.check_name for c in event.checks if not c.passed and c.severity=="CRITICAL"],
                   "pipeline_name": "data_quality_gate"},
        )
        return {"status": "blocked", "pipeline_blocked": True}

    _logger.info("Data quality gate passed",
                 extra={"n_warnings": event.warning_count(), "pipeline_name": "data_quality_gate"})
    return {"status": "ok", "pipeline_blocked": False}

if __name__ == "__main__":
    asyncio.run(run())
