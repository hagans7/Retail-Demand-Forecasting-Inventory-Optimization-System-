"""Abstract base for business config repository."""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.entities.business_config import BusinessConfig


class BaseConfigRepository(ABC):
    """Contract for business_configs table.

    Redis-cached layer (TTL=300s) sits in front — cache miss falls through to DB.
    """

    @abstractmethod
    async def get_config(self, key: str) -> BusinessConfig | None:
        """Return config by key. None if not found — caller uses constant default."""

    @abstractmethod
    async def get_all_configs(self) -> list[BusinessConfig]:
        """Return all Category 3 configs for /config/business-rules GET."""

    @abstractmethod
    async def upsert_config(self, config: BusinessConfig) -> None:
        """Insert or update config. Always persists previous_value.

        Raises:
            PersistenceError: On DB write failure.
        """

    @abstractmethod
    async def get_config_history(self, key: str) -> list[BusinessConfig]:
        """Return all historical values for audit trail."""
