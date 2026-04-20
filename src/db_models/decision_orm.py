"""ORM models — V2 Decision Intelligence tables.

Three new tables:
    decision_simulations      — audit trail for all recommendations
    item_financial_assumptions — COGS structure per item (Category 3 input)
    item_elasticity_observed   — Category 4 learned parameters

Index strategy documented per table per query pattern.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean, Date, DateTime, Float, Index,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text

from src.db_models.base import Base


class DecisionSimulationORM(Base):
    """decision_simulations: immutable audit trail for all V2 recommendations.

    config_snapshot written once at creation; never updated.
    actual_outcome filled by feedback_recalibration_pipeline.

    Index strategy:
        (store_id, item_id, created_at) — paginated history per pair
        (status, created_at)            — feedback pipeline: PENDING window
        created_at DESC                 — dashboard: recent simulations
    """
    __tablename__ = "decision_simulations"

    simulation_id          : Mapped[str]           = mapped_column(
                                                        String(64), primary_key=True,
                                                        server_default=text("gen_random_uuid()::text")
                                                    )
    store_id               : Mapped[str]           = mapped_column(String(50), nullable=False)
    item_id                : Mapped[str]           = mapped_column(String(50), nullable=False)
    recommendation         : Mapped[str]           = mapped_column(String(10), nullable=False)
    decision_score         : Mapped[float]         = mapped_column(Float, nullable=False)
    predicted_roi          : Mapped[float | None]  = mapped_column(Float, nullable=True)
    probability_profitable : Mapped[float | None]  = mapped_column(Float, nullable=True)
    uncertainty_band       : Mapped[dict | None]   = mapped_column(JSONB, nullable=True)
    risk_notes             : Mapped[dict]          = mapped_column(JSONB, nullable=False, default=list)
    recommended_action     : Mapped[str | None]    = mapped_column(Text, nullable=True)
    # Frozen at creation — never updated
    config_snapshot        : Mapped[dict]          = mapped_column(JSONB, nullable=False, default=dict)
    # For feedback recalibration
    predicted_uplift_pct   : Mapped[float | None]  = mapped_column(Float, nullable=True)
    promo_discount_pct     : Mapped[float | None]  = mapped_column(Float, nullable=True)
    # Resolution
    status                 : Mapped[str]           = mapped_column(String(30), nullable=False,
                                                                    default="PENDING")
    actual_outcome         : Mapped[dict | None]   = mapped_column(JSONB, nullable=True)
    override_flag          : Mapped[bool]          = mapped_column(Boolean, nullable=False, default=False)
    created_at             : Mapped[datetime]      = mapped_column(DateTime(timezone=True),
                                                                    server_default=func.now())
    resolved_at            : Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Feedback pipeline: find PENDING simulations in age window
        Index("idx_decision_status_time",   "status", "created_at"),
        # Audit: history per store-item pair
        Index("idx_decision_pair_time",     "store_id", "item_id", "created_at"),
        # Dashboard: latest simulations
        Index("idx_decision_created_desc",  "created_at"),
    )


class ItemFinancialAssumptionORM(Base):
    """item_financial_assumptions: COGS and cost structure per item.

    Sentinel row: item_id='__default__' always exists (seeded in migration 001).
    Query pattern: look up item_id first; fall through to __default__ if missing.

    No index needed beyond PRIMARY KEY — table is small (≤ 51 rows: 50 items + default).
    """
    __tablename__ = "item_financial_assumptions"

    item_id              : Mapped[str]          = mapped_column(String(50), primary_key=True)
    cogs_pct             : Mapped[float]        = mapped_column(Float, nullable=False)
    promo_fixed_cost     : Mapped[float]        = mapped_column(Float, nullable=False, default=0.0)
    holding_cost_per_day : Mapped[float]        = mapped_column(Float, nullable=False, default=0.0)
    updated_by           : Mapped[str | None]   = mapped_column(String(100), nullable=True)
    updated_at           : Mapped[datetime]     = mapped_column(DateTime(timezone=True),
                                                                 server_default=func.now(),
                                                                 onupdate=func.now())
    notes                : Mapped[str | None]   = mapped_column(Text, nullable=True)


class ItemElasticityObservedORM(Base):
    """item_elasticity_observed: Category 4 learned parameters.

    Updated by feedback_recalibration_pipeline (weekly) via EMA.
    EMA formula in SQL ON CONFLICT to ensure atomic update:
        elasticity_observed = 0.3 × new + 0.7 × existing

    Index strategy:
        PRIMARY KEY (item_id, store_id) — O(1) lookup per simulation call
        (last_calibrated_at) — pipeline: find recently updated items
    """
    __tablename__ = "item_elasticity_observed"

    item_id              : Mapped[str]          = mapped_column(String(50), nullable=False, primary_key=True)
    store_id             : Mapped[str]          = mapped_column(String(50), nullable=False, primary_key=True)
    elasticity_initial   : Mapped[float]        = mapped_column(Float, nullable=False)
    elasticity_observed  : Mapped[float]        = mapped_column(Float, nullable=False)
    n_observations       : Mapped[int]          = mapped_column(Integer, nullable=False, default=0)
    last_calibrated_at   : Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accuracy_score       : Mapped[float | None] = mapped_column(Float, nullable=True)
    source               : Mapped[str]          = mapped_column(String(30), nullable=False,
                                                                 default="initial_estimate")

    __table_args__ = (
        Index("idx_elasticity_last_cal", "last_calibrated_at"),
    )
