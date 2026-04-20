"""Override forecast service — human planner overrides model forecast."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from src.core.logging.logger import get_logger
from src.entities.override_event import OverrideEvent, OverrideType
from src.interfaces.base_forecast_repository import BaseForecastRepository


class OverrideForecastService:
    """Applies a human planner override to an existing forecast.

    Stores override event for audit and V3 training signal.
    Does NOT retrain the model — override is a one-time manual correction.
    """

    def __init__(self, forecast_repo: BaseForecastRepository) -> None:
        self._forecasts = forecast_repo
        self._logger    = get_logger(__name__)

    async def execute(
        self,
        store_id: str,
        item_id: str,
        target_date: date,
        override_qty: int,
        reason: str,
        user_id: str,
    ) -> OverrideEvent:
        existing = await self._forecasts.get_forecast(store_id, item_id, target_date)
        system_recommendation = {
            "predicted_sales": existing.daily_forecasts[0].predicted_sales if existing else None,
            "date": str(target_date),
        }
        event = OverrideEvent(
            event_id=str(uuid.uuid4()),
            store_id=store_id, item_id=item_id,
            override_type=OverrideType.FORECAST_MANUAL,
            system_recommendation=system_recommendation,
            human_override={"value": override_qty, "date": str(target_date)},
            override_reason=reason,
            user_id=user_id,
            created_at=datetime.now(tz=timezone.utc),
        )
        self._logger.info(
            "Forecast override recorded",
            extra={"store_id": store_id, "item_id": item_id,
                   "override_qty": override_qty, "operation": "override_forecast"},
        )
        return event
