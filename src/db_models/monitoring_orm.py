"""ORM models — monitoring and analytics tables."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Float, Index,
    Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.db_models.base import Base


class MonitoringMetricORM(Base):
    """monitoring_metrics: time-series metric storage.

    Used by: evaluate_forecast_accuracy (daily), feedback_recalibration (weekly).
    Includes V2 simulation drift metrics (metric_name prefix: 'decision_').
    """
    __tablename__ = "monitoring_metrics"

    metric_id         : Mapped[int]          = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    metric_name       : Mapped[str]          = mapped_column(String(100), nullable=False)
    metric_value      : Mapped[float]        = mapped_column(Float, nullable=False)
    segment           : Mapped[str | None]   = mapped_column(String(50), nullable=True)
    computed_at       : Mapped[datetime]     = mapped_column(DateTime(timezone=True), nullable=False)
    model_version     : Mapped[str | None]   = mapped_column(String(128), nullable=True)
    rolling_7d_value  : Mapped[float | None] = mapped_column(Float, nullable=True)
    rolling_28d_value : Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        # Primary query pattern: time-series by metric_name
        Index("idx_monitoring_name_time", "metric_name", "computed_at"),
    )


class AnalyticsSnapshotORM(Base):
    """analytics_snapshots: weekly business analytics aggregate."""
    __tablename__ = "analytics_snapshots"

    snapshot_id          : Mapped[str]      = mapped_column(String(64), primary_key=True)
    period_start         : Mapped[date]     = mapped_column(Date, nullable=False)
    period_end           : Mapped[date]     = mapped_column(Date, nullable=False)
    metrics              : Mapped[dict]     = mapped_column(JSONB, nullable=False, default=dict)
    revenue_metrics      : Mapped[dict]     = mapped_column(JSONB, nullable=False, default=dict)
    promo_effectiveness  : Mapped[dict]     = mapped_column(JSONB, nullable=False, default=dict)
    computed_at          : Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                            server_default=func.now())

    __table_args__ = (
        Index("idx_analytics_snapshot_time", "computed_at"),
    )


class HypothesisResultORM(Base):
    """hypothesis_results: weekly automated hypothesis test outputs."""
    __tablename__ = "hypothesis_results"

    result_id       : Mapped[int]     = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    hypothesis_id   : Mapped[str]     = mapped_column(String(50), nullable=False)
    current_value   : Mapped[float]   = mapped_column(Float, nullable=False)
    baseline_value  : Mapped[float]   = mapped_column(Float, nullable=False)
    deviation_pct   : Mapped[float]   = mapped_column(Float, nullable=False)
    status          : Mapped[str]     = mapped_column(String(30), nullable=False)
    period_start    : Mapped[date]    = mapped_column(Date, nullable=False)
    period_end      : Mapped[date]    = mapped_column(Date, nullable=False)
    sample_size     : Mapped[int]     = mapped_column(Integer, nullable=False)
    alert_triggered : Mapped[bool]    = mapped_column(Boolean, nullable=False, default=False)
    computed_at     : Mapped[datetime]= mapped_column(DateTime(timezone=True),
                                                       server_default=func.now())

    __table_args__ = (
        Index("idx_hypothesis_id_period", "hypothesis_id", "period_end"),
    )


class DriftMetricORM(Base):
    """drift_metrics: PSI-based feature drift and target distribution shift."""
    __tablename__ = "drift_metrics"

    metric_id       : Mapped[int]          = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    feature_name    : Mapped[str]          = mapped_column(String(60), nullable=False)
    psi_score       : Mapped[float | None] = mapped_column(Float, nullable=True)
    shift_pct       : Mapped[float | None] = mapped_column(Float, nullable=True)
    severity        : Mapped[str]          = mapped_column(String(20), nullable=False)
    current_mean    : Mapped[float]        = mapped_column(Float, nullable=False)
    training_mean   : Mapped[float]        = mapped_column(Float, nullable=False)
    current_std     : Mapped[float]        = mapped_column(Float, nullable=False)
    training_std    : Mapped[float]        = mapped_column(Float, nullable=False)
    computed_at     : Mapped[datetime]     = mapped_column(DateTime(timezone=True),
                                                            server_default=func.now())

    __table_args__ = (
        # Dashboard queries: recent drift by severity
        Index("idx_drift_time_severity", "computed_at", "severity"),
    )
