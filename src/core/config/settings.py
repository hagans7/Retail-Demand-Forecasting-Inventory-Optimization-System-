"""Application settings — Category 2 (Infrastructure Config).

All values come from environment variables. Sensitive values have no defaults.
Business rules (safety factors, decision weights) are NOT here — they live in
the business_configs DB table (Category 3).

Usage:
    from src.core.config.settings import settings
    db_url = settings.database_url
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str
    """postgresql+asyncpg://user:pass@host:5432/db — required, no default."""

    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------
    redis_url: str
    """redis://host:6379/0 — required."""

    celery_broker_url: str
    celery_result_backend: str

    redis_cache_ttl_seconds: int = 300
    """Category 3 config cache TTL (5 minutes)."""

    forecast_cache_ttl_seconds: int = 14400
    """Forecast result cache TTL (4 hours)."""

    # ------------------------------------------------------------------
    # MinIO
    # ------------------------------------------------------------------
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_secure: bool = False
    model_store_bucket: str = "ml-models"

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    log_env: str = "dev"
    """'dev' → human-readable text; 'prod' → JSON with file rotation."""

    debug: bool = False

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    app_name: str = "Retail Decision Platform"
    app_version: str = "1.0.0"

    model_config = SettingsConfigDict(
        protected_namespaces=('settings_',),
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
"""Singleton settings instance. Import this, not Settings directly."""
