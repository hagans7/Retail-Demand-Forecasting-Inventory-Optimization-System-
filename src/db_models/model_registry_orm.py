"""ORM model — model_registry table.

Three rows registered per training run (q40, q60, q80).
Shared version_tag links them; only q60 with is_production=True is active.

Index strategy:
    (is_production, quantile_level, created_at) — fast production model lookup
    (version_tag) — multi-quantile retrieval per training run
"""
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


class ModelRegistryORM(Base):
    __tablename__ = "model_registry"

    version_id              : Mapped[str]            = mapped_column(String(128), primary_key=True)
    version_tag             : Mapped[str]            = mapped_column(String(64), nullable=False)
    quantile_level          : Mapped[float]          = mapped_column(Float, nullable=False)
    algorithm               : Mapped[str]            = mapped_column(String(64), nullable=False)
    features                : Mapped[dict]           = mapped_column(JSONB, nullable=False)
    target                  : Mapped[str]            = mapped_column(String(32), nullable=False)
    loss                    : Mapped[str]            = mapped_column(String(64), nullable=False)
    best_iteration          : Mapped[int]            = mapped_column(Integer, nullable=False)
    trained_on_date         : Mapped[datetime]       = mapped_column(DateTime(timezone=True))
    val_mae                 : Mapped[float]          = mapped_column(Float, nullable=False)
    val_mae_promo           : Mapped[float]          = mapped_column(Float, nullable=False)
    val_uf_promo_pct        : Mapped[float]          = mapped_column(Float, nullable=False)
    naive_mae               : Mapped[float]          = mapped_column(Float, nullable=False)
    artifact_path           : Mapped[str | None]     = mapped_column(String(512), nullable=True)
    # Lineage fields
    training_data_start     : Mapped[date | None]    = mapped_column(Date, nullable=True)
    training_data_end       : Mapped[date | None]    = mapped_column(Date, nullable=True)
    training_data_rows      : Mapped[int]            = mapped_column(Integer, nullable=False, default=0)
    training_seconds        : Mapped[float]          = mapped_column(Float, nullable=False, default=0.0)
    training_data_hash      : Mapped[str | None]     = mapped_column(String(64), nullable=True)
    # Promotion state
    is_production           : Mapped[bool]           = mapped_column(Boolean, nullable=False, default=False)
    promoted_at             : Mapped[datetime | None]= mapped_column(DateTime(timezone=True), nullable=True)
    # Archival
    archived                : Mapped[bool]           = mapped_column(Boolean, nullable=False, default=False)
    archived_at             : Mapped[datetime | None]= mapped_column(DateTime(timezone=True), nullable=True)
    created_at              : Mapped[datetime]       = mapped_column(DateTime(timezone=True),
                                                                     server_default=func.now())

    __table_args__ = (
        # Fast production lookup: is_production=True, quantile=0.60
        Index("idx_registry_production", "is_production", "quantile_level", "created_at"),
        # Multi-quantile retrieval per training run
        Index("idx_registry_version_tag", "version_tag"),
        # Archival pipeline: non-production, non-archived, by date
        Index("idx_registry_archival", "is_production", "archived", "created_at"),
    )
