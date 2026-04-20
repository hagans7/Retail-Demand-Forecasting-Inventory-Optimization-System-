"""Repository providers — wired with DB session and Redis."""
from __future__ import annotations

import redis.asyncio as aioredis
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.interfaces.base_config_repository import BaseConfigRepository
from src.interfaces.base_decision_repository import BaseDecisionRepository
from src.interfaces.base_elasticity_repository import BaseElasticityRepository
from src.interfaces.base_forecast_repository import BaseForecastRepository
from src.providers.infrastructure import get_db_session, get_redis_client


def get_config_repo(
    db: AsyncSession = Depends(get_db_session),
    redis: aioredis.Redis = Depends(get_redis_client),
) -> BaseConfigRepository:
    from src.repositories.config_repository import ConfigRepository
    return ConfigRepository(db_session=db, redis_client=redis)


def get_forecast_repo(
    db: AsyncSession = Depends(get_db_session),
) -> BaseForecastRepository:
    from src.repositories.forecast_repository import ForecastRepository
    return ForecastRepository(db_session=db)


def get_decision_repo(
    db: AsyncSession = Depends(get_db_session),
) -> BaseDecisionRepository:
    from src.repositories.decision_repository import DecisionRepository
    return DecisionRepository(db_session=db)


def get_elasticity_repo(
    db: AsyncSession = Depends(get_db_session),
) -> BaseElasticityRepository:
    from src.repositories.elasticity_repository import ElasticityRepository
    return ElasticityRepository(db_session=db)


def get_monitoring_repo(
    db: AsyncSession = Depends(get_db_session),
):
    from src.repositories.monitoring_repository import MonitoringRepository
    return MonitoringRepository(db_session=db)
