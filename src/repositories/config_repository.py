"""Config repository — business_configs table with Redis caching."""
from __future__ import annotations

import json
from datetime import datetime

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config.settings import settings
from src.core.exceptions.app_exceptions import CacheError, PersistenceError
from src.core.logging.logger import get_logger
from src.db_models.operational_orm import BusinessConfigORM
from src.entities.business_config import BusinessConfig
from src.interfaces.base_config_repository import BaseConfigRepository

CACHE_TTL = settings.redis_cache_ttl_seconds


class ConfigRepository(BaseConfigRepository):
    """Category 3 config storage with Redis write-through cache.

    Cache key: "config:{config_key}"
    TTL: 300s (5 minutes). Invalidated on every upsert.
    """

    def __init__(self, db_session: AsyncSession, redis_client: aioredis.Redis) -> None:
        self._db = db_session
        self._redis = redis_client
        self._logger = get_logger(__name__)

    async def get_config(self, key: str) -> BusinessConfig | None:
        cache_key = f"config:{key}"
        try:
            cached = await self._redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                return self._to_entity(data)
        except Exception:
            pass  # cache miss → fall through to DB

        row = await self._db.get(BusinessConfigORM, key)
        if row is None:
            return None
        entity = self._orm_to_entity(row)
        try:
            await self._redis.setex(cache_key, CACHE_TTL, json.dumps(self._entity_to_dict(entity), default=str))
        except Exception:
            pass  # cache write failure is non-critical
        return entity

    async def get_all_configs(self) -> list[BusinessConfig]:
        result = await self._db.execute(select(BusinessConfigORM))
        rows = result.scalars().all()
        return [self._orm_to_entity(r) for r in rows]

    async def upsert_config(self, config: BusinessConfig) -> None:
        try:
            existing = await self._db.get(BusinessConfigORM, config.config_key)
            if existing:
                existing.config_value   = {"value": config.config_value}
                existing.reason         = config.reason
                existing.updated_by     = config.updated_by
                existing.previous_value = existing.config_value
            else:
                self._db.add(BusinessConfigORM(
                    config_key=config.config_key,
                    config_value={"value": config.config_value},
                    config_type=config.config_type,
                    updated_by=config.updated_by,
                    reason=config.reason,
                    previous_value=None,
                ))
            await self._db.commit()
            # Invalidate cache
            try:
                await self._redis.delete(f"config:{config.config_key}")
            except Exception:
                pass
        except Exception as e:
            await self._db.rollback()
            raise PersistenceError(f"upsert_config failed for {config.config_key}: {e}") from e

    async def get_config_history(self, key: str) -> list[BusinessConfig]:
        # Simple implementation: return current + previous_value as history
        row = await self._db.get(BusinessConfigORM, key)
        if row is None:
            return []
        return [self._orm_to_entity(row)]

    # ------------------------------------------------------------------
    def _orm_to_entity(self, row: BusinessConfigORM) -> BusinessConfig:
        raw = row.config_value
        value = raw.get("value", raw) if isinstance(raw, dict) else raw
        return BusinessConfig(
            config_key=row.config_key,
            config_value=value,
            config_type=row.config_type,
            updated_by=row.updated_by,
            updated_at=row.updated_at,
            reason=row.reason,
            previous_value=row.previous_value,
        )

    def _to_entity(self, data: dict) -> BusinessConfig:
        return BusinessConfig(
            config_key=data["config_key"],
            config_value=data["config_value"],
            config_type=data.get("config_type", "str"),
            updated_by=data.get("updated_by", ""),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            reason=data.get("reason", ""),
            previous_value=data.get("previous_value"),
        )

    def _entity_to_dict(self, e: BusinessConfig) -> dict:
        return {
            "config_key":    e.config_key,
            "config_value":  e.config_value,
            "config_type":   e.config_type,
            "updated_by":    e.updated_by,
            "updated_at":    e.updated_at.isoformat(),
            "reason":        e.reason,
            "previous_value": e.previous_value,
        }
