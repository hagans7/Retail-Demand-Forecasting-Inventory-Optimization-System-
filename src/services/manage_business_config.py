"""Manage business config service — validated Category 3 config writes."""
from __future__ import annotations

from datetime import datetime, timezone

from src.core.constants.business_constants import SAFETY_BOUNDS
from src.core.exceptions.app_exceptions import ConfigSafetyBoundsViolationError
from src.core.logging.logger import get_logger
from src.entities.business_config import BusinessConfig
from src.interfaces.base_config_repository import BaseConfigRepository


class ManageBusinessConfigService:
    """Validates and writes Category 3 runtime parameters.

    Enforces SAFETY_BOUNDS. Persists previous_value for audit.
    Cache invalidation handled by config_repository (Redis delete on write).
    """

    def __init__(self, config_repo: BaseConfigRepository) -> None:
        self._config = config_repo
        self._logger = get_logger(__name__)

    async def update(
        self,
        config_key: str,
        config_value,
        updated_by: str,
        reason: str,
    ) -> BusinessConfig:
        # Safety bounds check
        if config_key in SAFETY_BOUNDS and isinstance(config_value, (int, float)):
            lo, hi = SAFETY_BOUNDS[config_key]
            if not (lo <= float(config_value) <= hi):
                raise ConfigSafetyBoundsViolationError(
                    f"{config_key}={config_value} outside bounds [{lo}, {hi}]"
                )

        existing = await self._config.get_config(config_key)
        prev_val = existing.config_value if existing else None

        cfg = BusinessConfig(
            config_key=config_key,
            config_value=config_value,
            config_type=type(config_value).__name__,
            updated_by=updated_by,
            updated_at=datetime.now(tz=timezone.utc),
            reason=reason,
            previous_value=prev_val,
        )
        await self._config.upsert_config(cfg)
        self._logger.info(
            "Business config updated",
            extra={"config_key": config_key, "previous": prev_val,
                   "new_value": config_value, "operation": "manage_business_config"},
        )
        return cfg

    async def get(self, config_key: str) -> BusinessConfig | None:
        return await self._config.get_config(config_key)

    async def get_all(self) -> list[BusinessConfig]:
        return await self._config.get_all_configs()
