"""Forecast repository — forecast_results table."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions.app_exceptions import PersistenceError
from src.core.logging.logger import get_logger
from src.db_models.forecast_orm import ForecastORM
from src.entities.forecast import ColdStartTier, DailyForecast, ForecastResult
from src.interfaces.base_forecast_repository import BaseForecastRepository


class ForecastRepository(BaseForecastRepository):
    """CRUD for forecast_results — one row per store-item-date."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session
        self._logger = get_logger(__name__)

    async def save_forecast(self, result: ForecastResult) -> None:
        try:
            for daily in result.daily_forecasts:
                row = ForecastORM(
                    forecast_id=str(uuid.uuid4()),
                    store_id=result.store_id,
                    item_id=result.item_id,
                    forecast_date=daily.date,
                    predicted_sales=daily.predicted_sales,
                    lower_bound=daily.lower_bound,
                    upper_bound=daily.upper_bound,
                    revenue_estimate=daily.revenue_estimate,
                    feature_snapshot=daily.feature_snapshot,
                    model_version=result.model_version,
                    quantile_level=0.60,
                    cold_start_tier=result.cold_start_tier.value,
                )
                self._db.add(row)
            await self._db.commit()
        except Exception as e:
            await self._db.rollback()
            raise PersistenceError(f"save_forecast failed: {e}") from e

    async def get_forecast(
        self,
        store_id: str,
        item_id: str,
        forecast_date: date,
    ) -> ForecastResult | None:
        result = await self._db.execute(
            select(ForecastORM).where(
                ForecastORM.store_id    == store_id,
                ForecastORM.item_id     == item_id,
                ForecastORM.forecast_date == forecast_date,
            )
        )
        rows = result.scalars().all()
        if not rows:
            return None
        daily = [
            DailyForecast(
                date=r.forecast_date,
                predicted_sales=r.predicted_sales,
                lower_bound=r.lower_bound,
                upper_bound=r.upper_bound,
                revenue_estimate=r.revenue_estimate,
                feature_snapshot=r.feature_snapshot,
            )
            for r in rows
        ]
        return ForecastResult(
            store_id=store_id,
            item_id=item_id,
            horizon_days=len(daily),
            daily_forecasts=daily,
            model_version=rows[0].model_version,
            cold_start_tier=ColdStartTier(rows[0].cold_start_tier),
        )

    async def get_pending_evaluation(self, evaluation_date: date) -> list[dict]:
        result = await self._db.execute(
            select(ForecastORM).where(ForecastORM.forecast_date == evaluation_date)
        )
        rows = result.scalars().all()
        return [
            {
                "store_id": r.store_id,
                "item_id": r.item_id,
                "forecast_date": r.forecast_date,
                "predicted_sales": r.predicted_sales,
            }
            for r in rows
        ]
