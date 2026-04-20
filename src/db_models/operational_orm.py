"""ORM models — operational tables (override, scenario, data quality, config)."""
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


class OverrideEventORM(Base):
    """override_events: human planner overrides of system recommendations."""
    __tablename__ = "override_events"

    event_id              : Mapped[str]          = mapped_column(String(64), primary_key=True)
    store_id              : Mapped[str]          = mapped_column(String(50), nullable=False)
    item_id               : Mapped[str]          = mapped_column(String(50), nullable=False)
    override_type         : Mapped[str]          = mapped_column(String(30), nullable=False)
    system_recommendation : Mapped[dict]         = mapped_column(JSONB, nullable=False)
    human_override        : Mapped[dict]         = mapped_column(JSONB, nullable=False)
    override_reason       : Mapped[str]          = mapped_column(Text, nullable=False)
    user_id               : Mapped[str]          = mapped_column(String(100), nullable=False)
    created_at            : Mapped[datetime]     = mapped_column(DateTime(timezone=True),
                                                                  server_default=func.now())
    outcome               : Mapped[str | None]   = mapped_column(String(100), nullable=True)

    __table_args__ = (
        Index("idx_override_pair_time", "store_id", "item_id", "created_at"),
    )


class ScenarioRunORM(Base):
    """scenario_runs: all what-if simulation inputs and outputs."""
    __tablename__ = "scenario_runs"

    scenario_id   : Mapped[str]      = mapped_column(String(64), primary_key=True)
    store_id      : Mapped[str]      = mapped_column(String(50), nullable=False)
    item_id       : Mapped[str]      = mapped_column(String(50), nullable=False)
    scenario_type : Mapped[str]      = mapped_column(String(30), nullable=False)
    inputs        : Mapped[dict]     = mapped_column(JSONB, nullable=False)
    outputs       : Mapped[dict]     = mapped_column(JSONB, nullable=False)
    user_id       : Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at    : Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                      server_default=func.now())

    __table_args__ = (
        Index("idx_scenario_pair_time", "store_id", "item_id", "created_at"),
    )


class DataQualityEventORM(Base):
    """data_quality_events: pre-flight pipeline check results."""
    __tablename__ = "data_quality_events"

    event_id            : Mapped[int]    = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_date            : Mapped[date]   = mapped_column(Date, nullable=False)
    checks              : Mapped[dict]   = mapped_column(JSONB, nullable=False)
    all_critical_passed : Mapped[bool]   = mapped_column(Boolean, nullable=False)
    pipeline_blocked    : Mapped[bool]   = mapped_column(Boolean, nullable=False)
    fallback_strategy   : Mapped[str]    = mapped_column(String(30), nullable=False, default="NONE")
    created_at          : Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                            server_default=func.now())

    __table_args__ = (
        Index("idx_dq_run_date", "run_date"),
    )


class BusinessConfigORM(Base):
    """business_configs: Category 3 runtime-configurable parameters.

    Redis-cached (TTL=300s). Every write persists previous_value for audit.
    """
    __tablename__ = "business_configs"

    config_key     : Mapped[str]      = mapped_column(String(100), primary_key=True)
    config_value   : Mapped[dict]     = mapped_column(JSONB, nullable=False)
    config_type    : Mapped[str]      = mapped_column(String(20), nullable=False)
    updated_by     : Mapped[str]      = mapped_column(String(100), nullable=False)
    updated_at     : Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                       server_default=func.now(),
                                                       onupdate=func.now())
    reason         : Mapped[str]      = mapped_column(Text, nullable=False)
    previous_value : Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class BootstrapStatusORM(Base):
    """system_bootstrap_status: singleton row tracking Day-0 initialization state.

    Persisted to DB so state survives container restarts.
    Redis key 'bootstrap:status' caches this for fast reads (TTL=None).

    system_id is always 'default' — this is a singleton table.
    """
    __tablename__ = "system_bootstrap_status"

    system_id               : Mapped[str]           = mapped_column(String(32), primary_key=True,
                                                                     default="default")
    is_ready                : Mapped[bool]           = mapped_column(Boolean, nullable=False,
                                                                     default=False)
    technical_ready         : Mapped[bool]           = mapped_column(Boolean, nullable=False,
                                                                     default=False)
    recommended_ready       : Mapped[bool]           = mapped_column(Boolean, nullable=False,
                                                                     default=False)
    last_run_at             : Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                                      nullable=True)
    last_success_step       : Mapped[str | None]     = mapped_column(String(64), nullable=True)
    resume_from             : Mapped[str | None]     = mapped_column(String(64), nullable=True)
    sales_row_count         : Mapped[int | None]     = mapped_column(Integer, nullable=True)
    feature_pairs_covered   : Mapped[int | None]     = mapped_column(Integer, nullable=True)
    feature_days_min        : Mapped[int | None]     = mapped_column(Integer, nullable=True)
    feature_days_max        : Mapped[int | None]     = mapped_column(Integer, nullable=True)
    production_model_version: Mapped[str | None]     = mapped_column(String(128), nullable=True)
    model_val_mae_promo     : Mapped[float | None]   = mapped_column(Float, nullable=True)
    minio_bucket_exists     : Mapped[bool]           = mapped_column(Boolean, nullable=False,
                                                                     default=False)
    last_backfill_date      : Mapped[str | None]     = mapped_column(String(32), nullable=True)
    notes                   : Mapped[str | None]     = mapped_column(Text, nullable=True)
    updated_at              : Mapped[datetime]       = mapped_column(DateTime(timezone=True),
                                                                     server_default=func.now(),
                                                                     onupdate=func.now())
