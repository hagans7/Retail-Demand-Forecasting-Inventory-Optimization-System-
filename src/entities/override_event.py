"""Override event entity."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OverrideType(str, Enum):
    RESTOCK_QTY      = "RESTOCK_QTY"
    PROMO_PLAN       = "PROMO_PLAN"
    RISK_FLAG        = "RISK_FLAG"
    FORECAST_MANUAL  = "FORECAST_MANUAL"


@dataclass
class OverrideEvent:
    """Human planner override of system recommendation.

    actual_outcome filled post-hoc by feedback pipeline.
    Used as V3 training signal via override audit trail.
    """
    event_id             : str
    store_id             : str
    item_id              : str
    override_type        : OverrideType
    system_recommendation: dict
    human_override       : dict
    override_reason      : str
    user_id              : str
    created_at           : datetime
    outcome              : str | None = None

    def delta_magnitude(self) -> float:
        sys_val = self.system_recommendation.get("value", 0)
        hum_val = self.human_override.get("value", 0)
        if sys_val == 0:
            return 0.0
        return abs((hum_val - sys_val) / sys_val)

    def is_significant_override(self) -> bool:
        return self.delta_magnitude() > 0.20
