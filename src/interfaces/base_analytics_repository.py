"""Abstract base for analytics repository."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd

from src.entities.analytics_snapshot import WeeklyAnalyticsSnapshot
from src.entities.hypothesis_result import HypothesisResult


class BaseAnalyticsRepository(ABC):
    """Contract for reading raw sales data and writing analytics results."""

    @abstractmethod
    async def get_sales_for_period(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Return sales rows for period. Columns: store_id, item_id, date,
        sales, price, promo, weekday, month."""

    @abstractmethod
    async def get_revenue_for_period(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Return sales × price = revenue per row."""

    @abstractmethod
    async def get_item_promo_sensitivity(self) -> list[dict]:
        """Return pre-computed within-pair promo uplift per item.
        Format: [{item_id, avg_uplift_pct, n_promo_events}]"""

    @abstractmethod
    async def get_zero_sales_anomalies(self, consecutive_days: int) -> list[dict]:
        """Return pairs with >= consecutive_days of zero sales.
        Format: [{store_id, item_id, streak_len, start_date}]"""

    @abstractmethod
    async def save_hypothesis_results(
        self,
        results: list[HypothesisResult],
    ) -> None:
        """Batch insert hypothesis results."""

    @abstractmethod
    async def save_analytics_snapshot(
        self,
        snapshot: WeeklyAnalyticsSnapshot,
    ) -> None:
        """Upsert analytics snapshot."""

    @abstractmethod
    async def get_latest_analytics_snapshot(self) -> WeeklyAnalyticsSnapshot | None:
        """Return most recent snapshot or None if empty."""
