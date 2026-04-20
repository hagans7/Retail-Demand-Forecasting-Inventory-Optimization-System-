"""ORM models — forecast_results and feature_snapshots tables.

Index strategy documented per table:
    forecast_results   → (forecast_date, store_id, item_id) for API queries
    feature_snapshots  → (snapshot_date, store_id, item_id) for batch inference
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Float, Index,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.db_models.base import Base


class ForecastORM(Base):
    """forecast_results: one row per store-item-forecast_date.

    feature_snapshot JSONB: top-5 gain features at inference time.
    Used for post-hoc debugging without re-running feature engineering.
    """
    __tablename__ = "forecast_results"

    forecast_id       : Mapped[str]            = mapped_column(String(64), primary_key=True)
    store_id          : Mapped[str]            = mapped_column(String(50), nullable=False)
    item_id           : Mapped[str]            = mapped_column(String(50), nullable=False)
    forecast_date     : Mapped[date]           = mapped_column(Date, nullable=False)
    predicted_sales   : Mapped[float]          = mapped_column(Float, nullable=False)
    lower_bound       : Mapped[float]          = mapped_column(Float, nullable=False)
    upper_bound       : Mapped[float]          = mapped_column(Float, nullable=False)
    revenue_estimate  : Mapped[float | None]   = mapped_column(Float, nullable=True)
    feature_snapshot  : Mapped[dict | None]    = mapped_column(JSONB, nullable=True)
    model_version     : Mapped[str]            = mapped_column(String(100), nullable=False)
    quantile_level    : Mapped[float]          = mapped_column(Float, nullable=False, default=0.60)
    restock_qty       : Mapped[int | None]     = mapped_column(Integer, nullable=True)
    stockout_risk     : Mapped[str | None]     = mapped_column(String(20), nullable=True)
    safety_factor     : Mapped[float | None]   = mapped_column(Float, nullable=True)
    reason_codes      : Mapped[dict | None]    = mapped_column(JSONB, nullable=True)
    cold_start_tier   : Mapped[str]            = mapped_column(String(20), nullable=False, default="NONE")
    generated_at      : Mapped[datetime]       = mapped_column(DateTime(timezone=True),
                                                               server_default=func.now())

    __table_args__ = (
        # Primary access pattern: single pair-date lookup (API on-demand)
        Index("idx_forecast_date_pair", "forecast_date", "store_id", "item_id"),
        # Batch evaluation: all forecasts for a given date
        Index("idx_forecast_date", "forecast_date"),
    )


class FeatureSnapshotORM(Base):
    """feature_snapshots: engineered features per store-item-date.

    history_days: count of days with data; used by cold start tier routing.
    Partitioned logically by snapshot_date — queries almost always filter on date.
    """
    __tablename__ = "feature_snapshots"

    id              : Mapped[int]   = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    store_id        : Mapped[str]   = mapped_column(String(50), nullable=False)
    item_id         : Mapped[str]   = mapped_column(String(50), nullable=False)
    snapshot_date   : Mapped[date]  = mapped_column(Date, nullable=False)
    # Lag features
    lag_7           : Mapped[float | None] = mapped_column(Float, nullable=True)
    lag_14          : Mapped[float | None] = mapped_column(Float, nullable=True)
    lag_21          : Mapped[float | None] = mapped_column(Float, nullable=True)
    # Rolling means
    rolling_mean_7  : Mapped[float | None] = mapped_column(Float, nullable=True)
    rolling_mean_14 : Mapped[float | None] = mapped_column(Float, nullable=True)
    rolling_mean_28 : Mapped[float | None] = mapped_column(Float, nullable=True)
    # Rolling std
    rolling_std_7   : Mapped[float | None] = mapped_column(Float, nullable=True)
    rolling_std_14  : Mapped[float | None] = mapped_column(Float, nullable=True)
    # Rolling CV
    rolling_cv_7    : Mapped[float | None] = mapped_column(Float, nullable=True)
    rolling_cv_14   : Mapped[float | None] = mapped_column(Float, nullable=True)
    # Weekday one-hot
    wd_0            : Mapped[int | None]   = mapped_column(Integer, nullable=True)
    wd_1            : Mapped[int | None]   = mapped_column(Integer, nullable=True)
    wd_2            : Mapped[int | None]   = mapped_column(Integer, nullable=True)
    wd_3            : Mapped[int | None]   = mapped_column(Integer, nullable=True)
    wd_4            : Mapped[int | None]   = mapped_column(Integer, nullable=True)
    wd_5            : Mapped[int | None]   = mapped_column(Integer, nullable=True)
    wd_6            : Mapped[int | None]   = mapped_column(Integer, nullable=True)
    # Cyclic calendar
    month_sin       : Mapped[float | None] = mapped_column(Float, nullable=True)
    month_cos       : Mapped[float | None] = mapped_column(Float, nullable=True)
    doy_sin         : Mapped[float | None] = mapped_column(Float, nullable=True)
    doy_cos         : Mapped[float | None] = mapped_column(Float, nullable=True)
    week_of_month   : Mapped[int | None]   = mapped_column(Integer, nullable=True)
    # Promo features
    promo           : Mapped[int | None]   = mapped_column(Integer, nullable=True)
    promo_streak_day: Mapped[int | None]   = mapped_column(Integer, nullable=True)
    days_since_last_promo: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Metadata
    history_days    : Mapped[int]          = mapped_column(Integer, nullable=False, default=0)
    created_at      : Mapped[datetime]     = mapped_column(DateTime(timezone=True),
                                                            server_default=func.now())

    __table_args__ = (
        # Primary batch inference query: all pairs for a date
        Index("idx_snapshot_date_pair", "snapshot_date", "store_id", "item_id"),
        # Unique constraint: one row per pair-date
        UniqueConstraint("store_id", "item_id", "snapshot_date",
                         name="uq_feature_snapshot_pair_date"),
    )
