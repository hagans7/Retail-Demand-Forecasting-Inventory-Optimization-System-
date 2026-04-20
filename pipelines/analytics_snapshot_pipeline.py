"""Analytics snapshot pipeline — weekly Monday 07:00."""
from __future__ import annotations
import asyncio
from datetime import date
from src.core.logging.logger import get_logger
_logger = get_logger(__name__)

async def run(run_date: str | None = None) -> dict:
    today = date.fromisoformat(run_date) if run_date else date.today()
    _logger.info("Analytics snapshot pipeline started",
                 extra={"run_date": str(today), "pipeline_name": "analytics_snapshot"})
    from src.providers.infrastructure import _session_factory
    from src.repositories.analytics_repository import AnalyticsRepository
    from src.services.generate_analytics_snapshot import GenerateAnalyticsSnapshotService

    async with _session_factory() as db:
        svc      = GenerateAnalyticsSnapshotService(AnalyticsRepository(db))
        snapshot = await svc.execute(today)

    _logger.info("Analytics snapshot complete",
                 extra={"snapshot_id": snapshot.snapshot_id,
                        "pipeline_name": "analytics_snapshot"})
    return {"status": "ok", "snapshot_id": snapshot.snapshot_id}

if __name__ == "__main__":
    asyncio.run(run())
