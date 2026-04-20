"""Analytics repository — raw sales reads + analytics result writes."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions.app_exceptions import PersistenceError
from src.core.logging.logger import get_logger
from src.db_models.monitoring_orm import AnalyticsSnapshotORM, HypothesisResultORM
from src.entities.analytics_snapshot import WeeklyAnalyticsSnapshot
from src.entities.hypothesis_result import HypothesisResult
from src.interfaces.base_analytics_repository import BaseAnalyticsRepository


class AnalyticsRepository(BaseAnalyticsRepository):
    """Reads raw sales_transactions; writes analytics results."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session
        self._logger = get_logger(__name__)

    async def get_sales_for_period(self, start_date: date, end_date: date) -> pd.DataFrame:
        result = await self._db.execute(
            text("""
                SELECT store_id, item_id, date, sales, price, promo, weekday, month
                FROM sales_transactions
                WHERE date BETWEEN :start AND :end
                ORDER BY store_id, item_id, date
            """),
            {"start": start_date, "end": end_date},
        )
        rows = result.fetchall()
        return pd.DataFrame(rows, columns=result.keys())

    async def get_revenue_for_period(self, start_date: date, end_date: date) -> pd.DataFrame:
        result = await self._db.execute(
            text("""
                SELECT store_id, item_id, date, sales, price, promo,
                       sales * price AS revenue
                FROM sales_transactions
                WHERE date BETWEEN :start AND :end
            """),
            {"start": start_date, "end": end_date},
        )
        rows = result.fetchall()
        return pd.DataFrame(rows, columns=result.keys())

    async def get_item_promo_sensitivity(self) -> list[dict]:
        result = await self._db.execute(
            text("""
                SELECT
                    item_id,
                    COUNT(CASE WHEN promo = 1 THEN 1 END) AS n_promo_days,
                    AVG(CASE WHEN promo = 1 THEN sales END) AS avg_sales_promo,
                    AVG(CASE WHEN promo = 0 THEN sales END) AS avg_sales_nopromo
                FROM sales_transactions
                GROUP BY item_id
                HAVING COUNT(CASE WHEN promo = 1 THEN 1 END) >= 20
            """)
        )
        rows = result.fetchall()
        out = []
        for r in rows:
            if r.avg_sales_nopromo and r.avg_sales_nopromo > 0:
                uplift = (r.avg_sales_promo - r.avg_sales_nopromo) / r.avg_sales_nopromo * 100
                out.append({
                    "item_id": r.item_id,
                    "n_promo_days": r.n_promo_days,
                    "avg_uplift_pct": round(uplift, 2),
                })
        return sorted(out, key=lambda x: x["avg_uplift_pct"], reverse=True)

    async def get_zero_sales_anomalies(self, consecutive_days: int) -> list[dict]:
        """Window function to find consecutive zero-sales streaks."""
        result = await self._db.execute(
            text("""
                WITH streaks AS (
                    SELECT store_id, item_id, date,
                           ROW_NUMBER() OVER (PARTITION BY store_id, item_id ORDER BY date)
                           - ROW_NUMBER() OVER (
                               PARTITION BY store_id, item_id, CASE WHEN sales=0 THEN 1 ELSE 0 END
                               ORDER BY date
                           ) AS streak_group
                    FROM sales_transactions
                    WHERE sales = 0
                )
                SELECT store_id, item_id, MIN(date) AS start_date, COUNT(*) AS streak_len
                FROM streaks
                GROUP BY store_id, item_id, streak_group
                HAVING COUNT(*) >= :min_days
                ORDER BY streak_len DESC
            """),
            {"min_days": consecutive_days},
        )
        return [
            {
                "store_id": r.store_id,
                "item_id": r.item_id,
                "streak_len": r.streak_len,
                "start_date": r.start_date,
            }
            for r in result.fetchall()
        ]

    async def save_hypothesis_results(self, results: list[HypothesisResult]) -> None:
        try:
            now = datetime.now(tz=timezone.utc)
            for r in results:
                self._db.add(HypothesisResultORM(
                    hypothesis_id=r.hypothesis_id,
                    current_value=r.current_value,
                    baseline_value=r.baseline_value,
                    deviation_pct=r.deviation_pct,
                    status=r.status.value,
                    period_start=r.period_start,
                    period_end=r.period_end,
                    sample_size=r.sample_size,
                    alert_triggered=r.alert_triggered,
                    computed_at=now,
                ))
            await self._db.commit()
        except Exception as e:
            await self._db.rollback()
            raise PersistenceError(f"save_hypothesis_results failed: {e}") from e

    async def save_analytics_snapshot(self, snapshot: WeeklyAnalyticsSnapshot) -> None:
        try:
            existing = await self._db.get(AnalyticsSnapshotORM, snapshot.snapshot_id)
            if existing:
                existing.metrics = snapshot.metrics
                existing.revenue_metrics = snapshot.revenue_metrics
                existing.promo_effectiveness = snapshot.promo_effectiveness
            else:
                self._db.add(AnalyticsSnapshotORM(
                    snapshot_id=snapshot.snapshot_id,
                    period_start=snapshot.period_start,
                    period_end=snapshot.period_end,
                    metrics=snapshot.metrics,
                    revenue_metrics=snapshot.revenue_metrics,
                    promo_effectiveness=snapshot.promo_effectiveness,
                ))
            await self._db.commit()
        except Exception as e:
            await self._db.rollback()
            raise PersistenceError(f"save_analytics_snapshot failed: {e}") from e

    async def get_latest_analytics_snapshot(self) -> WeeklyAnalyticsSnapshot | None:
        result = await self._db.execute(
            select(AnalyticsSnapshotORM).order_by(AnalyticsSnapshotORM.computed_at.desc()).limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return WeeklyAnalyticsSnapshot(
            snapshot_id=row.snapshot_id,
            period_start=row.period_start,
            period_end=row.period_end,
            computed_at=row.computed_at,
            metrics=row.metrics,
            revenue_metrics=row.revenue_metrics,
            promo_effectiveness=row.promo_effectiveness,
        )
