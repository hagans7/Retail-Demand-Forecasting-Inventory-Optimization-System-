"""Alembic environment — async SQLAlchemy with all ORM models imported."""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

# Import all ORM models so Alembic autogenerate can discover them
from src.db_models.base import Base
from src.db_models.forecast_orm import ForecastORM, FeatureSnapshotORM
from src.db_models.model_registry_orm import ModelRegistryORM
from src.db_models.monitoring_orm import (
    MonitoringMetricORM, AnalyticsSnapshotORM,
    HypothesisResultORM, DriftMetricORM,
)
from src.db_models.operational_orm import (
    OverrideEventORM, ScenarioRunORM,
    DataQualityEventORM, BusinessConfigORM,
)
from src.db_models.decision_orm import (
    DecisionSimulationORM,
    ItemFinancialAssumptionORM,
    ItemElasticityObservedORM,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    from src.core.config.settings import settings
    return settings.database_url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(url=url, target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(get_url(), poolclass=pool.NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
