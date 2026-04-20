"""Decision feedback record entity — recalibration tracking."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.core.constants.decision_constants import ELASTICITY_DEVIATION_FLAG_PCT


class FeedbackStatus(str, Enum):
    PENDING            = "PENDING"
    RESOLVED           = "RESOLVED"
    UNRESOLVED         = "UNRESOLVED"
    CANCELLED_IN_STORE = "CANCELLED_IN_STORE"
    # CANCELLED_IN_STORE: promo approved by system but not executed in store.
    # Excluded from recalibration to prevent model poisoning.


@dataclass
class DecisionFeedbackRecord:
    """Tracks predicted vs actual promo outcome for elasticity recalibration.

    CANCELLED_IN_STORE status protects against model poisoning: when a promo
    was approved but never executed (e.g., staff forgot price labels), the
    resulting low sales would incorrectly suggest low elasticity if used.
    """
    simulation_id                    : str
    item_id                          : str
    store_id                         : str
    predicted_uplift_pct             : float
    actual_uplift_pct                : float | None = None
    deviation_pct                    : float | None = None   # actual - predicted
    elasticity_recalibration_delta   : float | None = None
    status                           : FeedbackStatus = FeedbackStatus.PENDING
    resolution_source                : str = "feedback_loop"
    flagged_for_review               : bool = False
    resolved_at                      : datetime | None = None

    def requires_elasticity_update(self) -> bool:
        return (
            self.status == FeedbackStatus.RESOLVED
            and self.actual_uplift_pct is not None
        )

    def is_significant_deviation(self) -> bool:
        if self.deviation_pct is None:
            return False
        return abs(self.deviation_pct) > ELASTICITY_DEVIATION_FLAG_PCT
