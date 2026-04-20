"""Infrastructure providers — singletons + per-request sessions."""
from __future__ import annotations

from functools import lru_cache

from fastapi.concurrency import asynccontextmanager
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config.settings import settings
from src.interfaces.base_model_client import BaseModelClient
from src.interfaces.base_storage_client import BaseStorageClient


@lru_cache(maxsize=1)
def get_storage_client() -> BaseStorageClient:
    """Singleton MinIO storage client."""
    from src.clients.storage_client import MinIOStorageClient
    return MinIOStorageClient()


@lru_cache(maxsize=1)
def get_model_client() -> BaseModelClient:
    """Singleton LightGBM model client. Loads model once per worker process."""
    from src.clients.model_client import LightGBMModelClient
    return LightGBMModelClient(storage_client=get_storage_client())


@lru_cache(maxsize=1)
def get_redis_client() -> aioredis.Redis:
    """Singleton async Redis client."""
    return aioredis.from_url(settings.redis_url, decode_responses=True)


_engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    echo=False,  # never echo SQL in production; use log_level=WARNING on sqlalchemy
)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def get_db_session() -> AsyncSession:
    """Per-request async DB session. Auto-closes on completion."""
    async with _session_factory() as session:
        yield session

@asynccontextmanager
async def make_worker_session():
    """Create a fresh SQLAlchemy engine + session for a single Celery task.
 
    IMPORTANT: Use this in ALL Celery task pipelines instead of _session_factory.
    Reason: if a previous task was killed by SoftTimeLimitExceeded, the module-level
    _engine pool may have corrupted asyncpg connections. A fresh engine avoids this.
 
    Usage:
        async with make_worker_session() as db:
            result = await db.execute(...)
 
    The engine is disposed when the context exits, releasing all connections.
    """
    engine = create_async_engine(
        settings.database_url,
        pool_size=2,          # small — each task only needs 1-2 connections
        max_overflow=2,
        pool_pre_ping=True,
        echo=False,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()