"""Monitoring repository — monitoring_metrics table."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions.app_exceptions import PersistenceError
from src.core.logging.logger import get_logger
from src.db_models.monitoring_orm import MonitoringMetricORM


class MonitoringRepository:
    """Writes and reads time-series monitoring metrics."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session
        self._logger = get_logger(__name__)

    async def save_daily_metrics(self, metrics: dict, model_version: str = "") -> None:
        try:
            now = datetime.now(tz=timezone.utc)
            for name, value in metrics.items():
                self._db.add(MonitoringMetricORM(
                    metric_name=name,
                    metric_value=float(value),
                    computed_at=now,
                    model_version=model_version or None,
                ))
            await self._db.commit()
        except Exception as e:
            await self._db.rollback()
            raise PersistenceError(f"save_daily_metrics failed: {e}") from e

    async def get_rolling_mae_promo(self, days: int) -> float | None:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
        result = await self._db.execute(
            select(func.avg(MonitoringMetricORM.metric_value)).where(
                MonitoringMetricORM.metric_name == "mae_promo",
                MonitoringMetricORM.computed_at >= cutoff,
            )
        )
        return result.scalar()

    async def get_last_retraining_trigger_date(self) -> datetime | None:
        result = await self._db.execute(
            select(func.max(MonitoringMetricORM.computed_at)).where(
                MonitoringMetricORM.metric_name == "retraining_triggered"
            )
        )
        return result.scalar()
