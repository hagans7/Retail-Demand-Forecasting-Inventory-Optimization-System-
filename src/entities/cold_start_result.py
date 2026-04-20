"""Cold start result entity."""
from __future__ import annotations

from dataclasses import dataclass

from src.core.constants.business_constants import SAFETY_FACTOR_COLD_START
from src.core.constants.model_constants import COLD_START_CONFIDENCE_NOTE
from src.entities.forecast import ColdStartTier


@dataclass
class ColdStartResult:
    """Output of HandleColdStartService for pairs with insufficient history.

    Invariants:
        safety_factor is always SAFETY_FACTOR_COLD_START (1.30)
        confidence is always 'LOW'
    """
    store_id         : str
    item_id          : str
    tier             : ColdStartTier
    proxy_source     : str      # e.g. "cross_store_item_average" | "lag_7_imputed"
    history_days     : int
    forecast_7d      : float    # total 7-day demand estimate
    daily_forecasts  : list     # list of DailyForecast (imported at runtime)
    safety_factor    : float = SAFETY_FACTOR_COLD_START
    confidence       : str   = "LOW"
    confidence_note  : str   = COLD_START_CONFIDENCE_NOTE
