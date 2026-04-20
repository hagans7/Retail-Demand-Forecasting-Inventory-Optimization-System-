"""Abstract base for forecast repository."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from src.entities.forecast import ForecastResult


class BaseForecastRepository(ABC):
    """Contract for forecast_results table CRUD."""

    @abstractmethod
    async def save_forecast(self, result: ForecastResult) -> None:
        """Persist a ForecastResult (all 7 DailyForecast rows).

        Raises:
            PersistenceError: On DB write failure.
        """

    @abstractmethod
    async def get_forecast(
        self,
        store_id: str,
        item_id: str,
        forecast_date: date,
    ) -> ForecastResult | None:
        """Return forecast for a specific pair-date. None if not found."""

    @abstractmethod
    async def get_pending_evaluation(
        self,
        evaluation_date: date,
    ) -> list[dict]:
        """Return forecast rows for pairs that have actuals available for evaluation_date."""
