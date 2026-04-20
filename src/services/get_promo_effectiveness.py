"""Get promo effectiveness service — ranked item promo uplift table."""
from __future__ import annotations

from src.core.constants.business_constants import PROMO_MIN_EXPOSURE_DAYS
from src.core.logging.logger import get_logger
from src.interfaces.base_analytics_repository import BaseAnalyticsRepository


class GetPromoEffectivenessService:
    """Returns ranked table of items by promo response.

    Items with < PROMO_MIN_EXPOSURE_DAYS promo events are excluded
    (insufficient data for reliable uplift estimate).
    Source: promo_effectiveness_baseline.csv data baked into analytics_repository.
    """

    def __init__(self, analytics_repo: BaseAnalyticsRepository) -> None:
        self._analytics = analytics_repo
        self._logger    = get_logger(__name__)

    async def execute(self, min_exposure_days: int | None = None) -> list[dict]:
        min_days = min_exposure_days or PROMO_MIN_EXPOSURE_DAYS
        items    = await self._analytics.get_item_promo_sensitivity()
        filtered = [i for i in items if i.get("n_promo_days", 0) >= min_days]
        self._logger.info(
            "Promo effectiveness computed",
            extra={"n_eligible": len(filtered), "min_days": min_days,
                   "operation": "get_promo_effectiveness"},
        )
        return filtered
