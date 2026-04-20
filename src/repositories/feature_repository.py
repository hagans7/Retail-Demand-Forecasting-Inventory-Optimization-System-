
"""Feature repository — feature_snapshots table."""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions.app_exceptions import FeatureStoreUnavailableError
from src.core.logging.logger import get_logger
from src.db_models.forecast_orm import FeatureSnapshotORM
from src.interfaces.base_feature_repository import BaseFeatureRepository


class FeatureRepository(BaseFeatureRepository):
    """Reads feature_snapshots table. Two primary access patterns:
        1. Single pair-date (on-demand API)
        2. All pairs for one date (nightly batch inference)
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session
        self._logger = get_logger(__name__)

    async def get_features_for_date(
        self,
        store_id: str,
        item_id: str,
        target_date: date,
    ) -> pd.DataFrame | None:
        try:
            result = await self._db.execute(
                select(FeatureSnapshotORM).where(
                    FeatureSnapshotORM.store_id == store_id,
                    FeatureSnapshotORM.item_id == item_id,
                    FeatureSnapshotORM.snapshot_date == target_date,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return self._row_to_df(row)
        except Exception as e:
            raise FeatureStoreUnavailableError(
                f"feature_store query failed: {e}"
            ) from e

    async def get_features_batch(self, target_date: date) -> pd.DataFrame:
        """Returns all ~2500 pairs for ONE snapshot_date — used by batch_inference pipeline.

        For training (all historical dates), use get_all_features_for_training() instead.
        """
        try:
            result = await self._db.execute(
                select(FeatureSnapshotORM).where(
                    FeatureSnapshotORM.snapshot_date == target_date
                )
            )
            rows = result.scalars().all()
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame([self._row_to_dict(r) for r in rows])
        except Exception as e:
            raise FeatureStoreUnavailableError(
                f"get_features_batch failed: {e}"
            ) from e

    async def get_all_features_for_training(self) -> pd.DataFrame:
        """Returns ALL rows from feature_snapshots for model training.

        Used by train_model.py only. Returns full history:
        ~4,565,000 rows (2500 pairs × 1826 days) loaded via raw SQL for performance.
        """
        from sqlalchemy import text
        try:
            result = await self._db.execute(
                text("""
                    SELECT store_id, item_id, snapshot_date, history_days,
                           lag_7, lag_14, lag_21,
                           rolling_mean_7, rolling_mean_14, rolling_mean_28,
                           rolling_std_7, rolling_std_14, rolling_cv_7, rolling_cv_14,
                           wd_0, wd_1, wd_2, wd_3, wd_4, wd_5, wd_6,
                           month_sin, month_cos, doy_sin, doy_cos, week_of_month,
                           promo, promo_streak_day, days_since_last_promo
                    FROM feature_snapshots
                    ORDER BY snapshot_date, store_id, item_id
                """)
            )
            rows = result.fetchall()
            cols = list(result.keys())
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame(rows, columns=cols)
        except Exception as e:
            raise FeatureStoreUnavailableError(
                f"get_all_features_for_training failed: {e}"
            ) from e

    async def get_history_days(self, store_id: str, item_id: str) -> int:
        try:
            result = await self._db.execute(
                select(func.count()).where(
                    FeatureSnapshotORM.store_id == store_id,
                    FeatureSnapshotORM.item_id == item_id,
                )
            )
            return result.scalar() or 0
        except Exception as e:
            raise FeatureStoreUnavailableError(
                f"get_history_days failed: {e}"
            ) from e

    # ------------------------------------------------------------------
    def _row_to_dict(self, row: FeatureSnapshotORM) -> dict:
        return {
            "store_id": row.store_id, "item_id": row.item_id,
            "snapshot_date": row.snapshot_date, "history_days": row.history_days,
            "lag_7": row.lag_7, "lag_14": row.lag_14, "lag_21": row.lag_21,
            "rolling_mean_7": row.rolling_mean_7, "rolling_mean_14": row.rolling_mean_14,
            "rolling_mean_28": row.rolling_mean_28,
            "rolling_std_7": row.rolling_std_7, "rolling_std_14": row.rolling_std_14,
            "rolling_cv_7": row.rolling_cv_7, "rolling_cv_14": row.rolling_cv_14,
            "wd_0": row.wd_0, "wd_1": row.wd_1, "wd_2": row.wd_2,
            "wd_3": row.wd_3, "wd_4": row.wd_4, "wd_5": row.wd_5, "wd_6": row.wd_6,
            "month_sin": row.month_sin, "month_cos": row.month_cos,
            "doy_sin": row.doy_sin, "doy_cos": row.doy_cos,
            "week_of_month": row.week_of_month,
            "promo": row.promo, "promo_streak_day": row.promo_streak_day,
            "days_since_last_promo": row.days_since_last_promo,
        }

    def _row_to_df(self, row: FeatureSnapshotORM) -> pd.DataFrame:
        return pd.DataFrame([self._row_to_dict(row)])